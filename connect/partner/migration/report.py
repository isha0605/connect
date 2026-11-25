import csv
from collections import defaultdict
from pathlib import Path

from frappe.utils import now_datetime

# Kinds of line that mean the data didn't move cleanly. A clean trial run has none of them.
PROBLEM_KINDS = (
	"unknown_fields",
	"automations_on",
	"failed",
	"conflicts",
	"unmatched",
	"missing",
	"gone",
	"files_failed",
)


class Report:
	"""What a run did, or would do: lines grouped by kind, such as "created" or "failed"."""

	def __init__(self):
		self.lines: dict[str, list[str]] = defaultdict(list)

	def add(self, kind: str, line: str) -> None:
		self.lines[kind].append(line)

	def merge(self, other: "Report") -> None:
		"""Adds another step's lines, such as the files a migration copied after saving its records."""
		for kind, lines in other.lines.items():
			self.lines[kind] += lines

	def get_counts(self) -> dict[str, int]:
		return {kind: len(lines) for kind, lines in sorted(self.lines.items())}

	def has_problems(self) -> bool:
		return any(self.lines.get(kind) for kind in PROBLEM_KINDS)

	def write(self, folder: str | Path) -> Path:
		"""Writes one CSV per kind and a summary into a new folder inside `folder`, and returns it."""
		target = Path(folder) / f"report-{now_datetime():%Y%m%d-%H%M%S}"
		target.mkdir(parents=True)
		for kind, lines in self.lines.items():
			with (target / f"{kind}.csv").open("w", newline="", encoding="utf-8") as file:
				writer = csv.writer(file)
				writer.writerow([kind])
				writer.writerows([line] for line in lines)

		summary = [f"{kind}: {count}" for kind, count in self.get_counts().items()]
		(target / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
		return target
