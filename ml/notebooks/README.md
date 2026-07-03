# ML notebooks

`model_development.ipynb` develops and evaluates the opportunity/suitability
index model: EDA, the spatial train/validation split, comparison across
7 model families, SHAP explanations, and a confusion-matrix/ROC view of the
model thresholded into a "high opportunity" classifier.

To re-run it:

```bash
pip install -r requirements.txt -r ml/notebooks/requirements-notebook.txt
export DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/bizintel
jupyter nbconvert --to notebook --execute --inplace ml/notebooks/model_development.ipynb
```

Or open it interactively with `jupyter lab`.

The notebook is exploratory - the model that actually ships is trained,
evaluated, and registered by `scripts/train_and_score_opportunity_model.py`.
