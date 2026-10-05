"""Repete os testes HTTP e compara a API com o artefato salvo no projeto."""

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import joblib
import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]


def solicitar(url, caminho, entrada=None):
    dados = None if entrada is None else json.dumps(entrada, allow_nan=False).encode()
    request = Request(
        url + caminho,
        data=dados,
        headers={"Content-Type": "application/json"} if dados is not None else {},
    )
    try:
        with urlopen(request, timeout=10) as resposta:
            return resposta.status, resposta.read().decode()
    except HTTPError as erro:
        return erro.code, erro.read().decode()


def verificar(url):
    entrada = json.loads((RAIZ / "exemplos/predicao.json").read_text())
    metadados = json.loads((RAIZ / "modelos/metadados.json").read_text())
    arquivo_modelo = RAIZ / "modelos/modelo.joblib"
    modelo = joblib.load(arquivo_modelo)
    colunas = metadados["colunas_entrada"]
    if list(modelo.feature_names_in_) != colunas:
        raise ValueError("A ordem das colunas do modelo difere dos metadados.")
    previsao_local = float(
        modelo.predict(pd.DataFrame([entrada["fechamentos"]], columns=colunas))[0]
    )
    registros = []

    def conferir(nome, caminho, esperado, payload=None, resultado=None):
        status, corpo = solicitar(url, caminho, payload)
        resposta = json.loads(corpo) if caminho != "/docs" else {"html_recebido": bool(corpo)}
        if status != esperado:
            raise ValueError(f"{nome}: HTTP {status}, esperado {esperado}. Resposta: {corpo}")
        if resultado is not None and resposta != resultado:
            raise ValueError(f"{nome}: a resposta não corresponde ao modelo local: {resposta}")
        registros.append({
            "caso": nome,
            "caminho": caminho,
            "entrada": payload,
            "status_http": status,
            "resposta": resposta,
        })
        print(f"OK: {nome} — HTTP {status}")
        return resposta

    conferir("serviço e modelo carregados", "/health", 200,
             resultado={"status": "ok", "modelo_carregado": True})
    previsao_api = conferir("predição igual ao artefato local", "/predict", 200, entrada, {
        "moeda": metadados["moeda"],
        "horizonte_dias": metadados["horizonte_dias"],
        "previsao_fechamento_usd": round(previsao_local, 2),
    })
    if not math.isfinite(previsao_api["previsao_fechamento_usd"]):
        raise ValueError("A previsão retornada não é finita.")

    precos = entrada["fechamentos"]
    casos = [
        ("campo ausente", {}),
        ("seis fechamentos", {"fechamentos": precos[:-1]}),
        ("oito fechamentos", {"fechamentos": precos + [100000]}),
        ("preço negativo", {"fechamentos": [-1] + precos[1:]}),
        ("preço zero", {"fechamentos": [0] + precos[1:]}),
        ("preço não finito", {"fechamentos": ["NaN"] + precos[1:]}),
        ("texto sem valor numérico", {"fechamentos": ["bitcoin"] + precos[1:]}),
        ("campo extra", {**entrada, "campo_desconhecido": 1}),
    ]
    for nome, payload in casos:
        conferir(nome, "/predict", 422, payload)
    conferir("documentação interativa", "/docs", 200)
    esquema = conferir("esquema OpenAPI", "/openapi.json", 200)
    if "post" not in esquema["paths"].get("/predict", {}):
        raise ValueError("A predição não está documentada no esquema OpenAPI.")
    if "get" not in esquema["paths"].get("/health", {}):
        raise ValueError("O health check não está documentado no esquema OpenAPI.")

    return {
        "executado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        "url_base": url,
        "modelo_sha256": hashlib.sha256(arquivo_modelo.read_bytes()).hexdigest(),
        "previsao_local_usd": previsao_local,
        "previsao_api_usd": previsao_api["previsao_fechamento_usd"],
        "previsao_confere_com_artefato_local": True,
        "total_casos": len(registros),
        "todos_aprovados": True,
        "casos": registros,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--saida", type=Path, default=RAIZ / "evidencias/verificacao-final.json")
    argumentos = parser.parse_args()
    try:
        relatorio = verificar(argumentos.url.rstrip("/"))
    except (OSError, URLError, ValueError, KeyError) as erro:
        print(f"Falha na verificação: {erro}", file=sys.stderr)
        return 1
    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n")
    print(f"{relatorio['total_casos']} casos aprovados. Evidência: {argumentos.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
