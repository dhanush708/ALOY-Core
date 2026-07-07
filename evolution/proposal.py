import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List


@dataclass
class ImprovementProposal:
    id: str
    problem: str
    evidence: str
    possible_solutions: List[str]
    recommended_solution: str
    affected_files: List[str]
    benefits: str
    risks: str
    implementation_plan: str
    status: str = "pending"  # pending, approved, rejected, applied
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "problem": self.problem,
            "evidence": self.evidence,
            "possible_solutions": self.possible_solutions,
            "recommended_solution": self.recommended_solution,
            "affected_files": self.affected_files,
            "benefits": self.benefits,
            "risks": self.risks,
            "implementation_plan": self.implementation_plan,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row) -> "ImprovementProposal":
        return cls(
            id=row["id"],
            problem=row["problem"],
            evidence=row["evidence"],
            possible_solutions=json.loads(row["possible_solutions"] or "[]"),
            recommended_solution=row["recommended_solution"],
            affected_files=json.loads(row["affected_files"] or "[]"),
            benefits=row["benefits"],
            risks=row["risks"],
            implementation_plan=row["implementation_plan"],
            status=row["status"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def to_markdown(self) -> str:
        solutions_list = "\n".join(f"- {s}" for s in self.possible_solutions)
        files_list = "\n".join(f"- `{f}`" for f in self.affected_files) or "*None*"
        return f"""# Self-Improvement Proposal: {self.id}

## Status: {self.status.upper()}
- **Created At**: {self.created_at}

## 1. Problem
{self.problem}

## 2. Evidence
{self.evidence}

## 3. Possible Solutions
{solutions_list}

## 4. Recommended Solution
{self.recommended_solution}

## 5. Affected Files
{files_list}

## 6. Expected Benefits
{self.benefits}

## 7. Risks & Mitigation
{self.risks}

## 8. Implementation Plan
{self.implementation_plan}
"""
