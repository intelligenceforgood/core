.PHONY: taxonomy-gen

taxonomy-gen:
	conda run -n i4g python scripts/codegen/taxonomy.py
