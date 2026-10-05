"""API que carrega o modelo treinado e prevê o fechamento seguinte."""

import json
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


PASTA_MODELOS = Path(__file__).resolve().parents[1] / "modelos"
JANELA_DIAS = 7
PrecoFechamento = Annotated[FiniteFloat, Field(gt=0)]


class EntradaPredicao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fechamentos: list[PrecoFechamento] = Field(
        min_length=JANELA_DIAS,
        max_length=JANELA_DIAS,
        description="Sete fechamentos em USD, do mais recente ao de seis dias antes.",
    )


class SaidaPredicao(BaseModel):
    moeda: str
    horizonte_dias: int
    previsao_fechamento_usd: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    # O modelo é carregado uma vez, antes de o serviço receber solicitações.
    modelo = joblib.load(PASTA_MODELOS / "modelo.joblib")
    metadados = json.loads((PASTA_MODELOS / "metadados.json").read_text(encoding="utf-8"))
    colunas = metadados["colunas_entrada"]

    if metadados["janela_dias"] != JANELA_DIAS:
        raise RuntimeError("A janela do modelo não corresponde às sete entradas da API.")
    if list(modelo.feature_names_in_) != colunas:
        raise RuntimeError("A ordem das entradas nos metadados não corresponde ao modelo.")

    app.state.modelo = modelo
    app.state.metadados = metadados
    yield


app = FastAPI(
    title="Predição do fechamento do Bitcoin",
    description="Previsão experimental do dia seguinte usando sete fechamentos conhecidos.",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    """Confirma que o serviço iniciou e carregou o modelo."""
    return {"status": "ok", "modelo_carregado": True}


@app.post("/predict", response_model=SaidaPredicao)
def predict(entrada: EntradaPredicao, request: Request):
    """Recebe os sete preços na mesma ordem utilizada pelo treinamento."""
    metadados = request.app.state.metadados
    dados_entrada = pd.DataFrame(
        [entrada.fechamentos], columns=metadados["colunas_entrada"]
    )
    previsao = float(request.app.state.modelo.predict(dados_entrada)[0])

    if not math.isfinite(previsao):
        raise HTTPException(status_code=422, detail="Essas entradas não produziram uma previsão finita.")

    return SaidaPredicao(
        moeda=metadados["moeda"],
        horizonte_dias=metadados["horizonte_dias"],
        previsao_fechamento_usd=round(previsao, 2),
    )
