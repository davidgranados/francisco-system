"""The eval cases: parsed from casos.yaml and checked against the tool registry."""

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.tools import REGISTRY
from evals.fixtures import FIXTURES, PARTNERS

CASES_PATH = Path(__file__).with_name("casos.yaml")

LIST_KEYS = (
    "ventas_nuevas",
    "compras_nuevas",
    "gastos_nuevos",
    "mermas_nuevas",
    "conteos_nuevos",
    "aportes_nuevos",
    "cierres_nuevos",
    "anuladas",
    "gastos_devueltos",
)
"""Rows a run added or changed; a case that names none of them expects none."""
SCALAR_KEYS = ("huevos", "tasa_hoy", "precios_caja_abierta", "pendientes_abiertos")
STATE_KEYS = (*LIST_KEYS, *SCALAR_KEYS)

Mention = str | list[str]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedCall(Strict):
    herramienta: str
    args: dict[str, Any] = Field(default_factory=dict)


class Turn(Strict):
    socio: str | None = None
    boton: Literal["confirmar", "cancelar"] | None = None
    como: str = "Francisco"
    llamadas: list[ExpectedCall] = Field(default_factory=list)
    prohibidas: list[str] = Field(default_factory=list)
    menciona: list[Mention] = Field(default_factory=list)
    pendiente: bool | None = None
    permitir_escrituras_extra: bool = False

    @model_validator(mode="after")
    def one_input(self) -> Self:
        if (self.socio is None) == (self.boton is None):
            raise ValueError("un turno es un mensaje del socio o un botón, no los dos")
        return self


class Case(Strict):
    id: str
    categoria: str
    fixture: str
    descripcion: str = ""
    turnos: list[Turn] = Field(min_length=1)
    estado: dict[str, Any] = Field(default_factory=dict)


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Case.model_validate(item) for item in raw]


def problems(cases: list[Case]) -> list[str]:
    """Everything in the cases that names a tool, argument, fixture or partner that is not there."""
    found: list[str] = []
    ids = [case.id for case in cases]
    found += [f"id repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for case in cases:
        where = case.id
        if case.fixture not in FIXTURES:
            found.append(f"{where}: no existe el fixture {case.fixture}")
        found += [
            f"{where}: estado desconocido {key}" for key in case.estado if key not in STATE_KEYS
        ]
        for number, turn in enumerate(case.turnos, 1):
            here = f"{where} turno {number}"
            if turn.como not in PARTNERS:
                found.append(f"{here}: no existe el socio {turn.como}")
            for name in turn.prohibidas:
                if name not in REGISTRY:
                    found.append(f"{here}: no existe la herramienta prohibida {name}")
            for call in turn.llamadas:
                tool = REGISTRY.get(call.herramienta)
                if tool is None:
                    found.append(f"{here}: no existe la herramienta {call.herramienta}")
                    continue
                fields = tool.input_model.model_fields
                found += [
                    f"{here}: {call.herramienta} no tiene el argumento {arg}"
                    for arg in call.args
                    if arg not in fields
                ]
    return found
