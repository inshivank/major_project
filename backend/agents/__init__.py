"""Agent implementations for CoreCare."""

from backend.agents.base import Agent, AgentResult
from backend.agents.patient_agent import PatientAgent, is_diagnosis_request, is_emergency
from backend.agents.stubs import ClinicalAgent, ReportAgent

__all__ = [
    "Agent",
    "AgentResult",
    "ClinicalAgent",
    "PatientAgent",
    "ReportAgent",
    "is_diagnosis_request",
    "is_emergency",
]
