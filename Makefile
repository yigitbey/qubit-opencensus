
.PHONY: publish

publish:
	python3 setup.py bdist_wheel upload -r local
