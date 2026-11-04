import pytest

from app.services.ml_terminology import ml_terminology_issue


@pytest.mark.parametrize("text, expected", [
    ("Compared machine learning models including XGBoost and scikit-learn.", True),
    ("Models: pandas, NumPy.", True),
    ("scikit-learn is a machine learning model.", True),
    ("Models such as NumPy and Random Forest.", True),
    ("Compared models using scikit-learn and XGBoost.", False),
    ("Trained scikit-learn models.", False),
    ("Compared models including Random Forest trained with scikit-learn.", False),
    ("Used NumPy and pandas for data preparation.", False),
    ("scikit-learn is not a model.", False),
    ("Models including Random Forest and XGBoost.", False),
    ("Model validation with sklearn.", False),
    # New Test Cases
    ("Models: NumPy", True),
    ("Models including sklearn\nOther facts", True),
    ("Models including XGBoost. Models including NumPy.", True),
    ("Models including NumPy or Random Forest.", True),
    ("Model: pandas", True),
    ("", False),
    ("Compared models including Random Forest; used NumPy for preprocessing.", False),
    ("Compared models including Random Forest trained with scikit-learn.", False),
    ("scikit-learn is not a model.", False),
])
def test_ml_terminology_issue(text: str, expected: bool):
    assert ml_terminology_issue(text) == expected
