PYTHON_VERSION=$(cat .python-version)
pyenv install -s "$PYTHON_VERSION" && pyenv local "$PYTHON_VERSION"
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
