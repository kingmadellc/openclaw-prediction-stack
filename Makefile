# CODEX: simple public regression entrypoints.

.PHONY: test ci-test

test:
	python3 -m pytest tests -q

ci-test:
	python -m pytest tests -q
