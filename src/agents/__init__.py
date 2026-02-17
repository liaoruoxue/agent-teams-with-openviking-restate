"""Agent layer — Manager, Coder, and Tester virtual objects."""

from src.agents.coder import coder
from src.agents.manager import manager
from src.agents.tester import tester

__all__ = ["manager", "coder", "tester"]
