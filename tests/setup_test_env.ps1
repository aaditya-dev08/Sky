Write-Output "🧪 Setting up test environment..."
python -m venv test_env
.\test_env\Scripts\Activate.ps1
pip install -e .
pip install pytest pytest-html
Write-Output "✅ Test environment ready!"
