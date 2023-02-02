import fastapi
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from typing import Union
import numpy as np

from src.kinopoisk_analyzer.FilmAnalyzer.numvisual import get_visualization
from src.kinopoisk_analyzer.FilmAnalyzer.builders import FilmParametersBuilder

app = FastAPI(debug=True)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/visualizations")
def read_item(prop: str = 'ratingKinopoisk', function: int = 1, consider_nones: int = 1, source: str = 'browser'):
    funcs = [
        len,
        np.mean,
        np.max,
        np.min,
        np.median
    ]

    builder = FilmParametersBuilder()
    builder.set_keyword('алиса')

    visual = get_visualization(properties_=['ratingKinopoisk'], apply_function=np.mean, consider_nones=False,
                               source=source, params=builder.build())

    return HTMLResponse(content=visual, status_code=200)
