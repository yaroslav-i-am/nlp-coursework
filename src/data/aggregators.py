import sys
from typing import Dict, List, Union, Tuple, Optional

from src.data.films_info.builders import FilmParametersBuilder
from src.data.films_info.functions import get_genres, get_countries
from src.data.requests import FilmListRequester, ReviewRequester, TopFilmsRequester
from src.utils.stylifiers import Stylers

REST_PAGE_SIZE = 20


def aggregate_films_by_letter() -> List:
    films_list = []
    cyrillic_lower_letters = 'аеёиоуыэюя'

    builder = FilmParametersBuilder()

    try:
        for letter in cyrillic_lower_letters:
            builder.set_keyword(letter)
            films_list.extend(FilmListAggregator(builder.build()).perform())
    except KeyboardInterrupt:
        print('Keyboard interrupt caught. Films returned.', file=sys.stderr)
        return films_list

    return films_list


def aggregate_films_by_params(params: dict) -> List:
    films_list = []
    try:
        films_list.extend(FilmListAggregator(params).perform())
    except KeyboardInterrupt:
        print('Keyboard interrupt caught. Films returned.', file=sys.stderr)
        return films_list

    return films_list


# def aggregate_reviews_by_ids(ids: list):
#


class FilmListAggregator:
    def __init__(self, params: dict):
        self.params = params
        print(params)
        self.film_list = []

    def perform(self) -> List:
        genres_list = get_genres()
        countries_list = get_countries()

        request_params = self.params
        if 'genres' in request_params:
            request_params['genres'] = [genres_list[request_params['genres']]]
        if 'countries' in request_params:
            request_params['countries'] = [countries_list[request_params['countries']]]

        print('AGGREGATOR:', Stylers.bold('PARAMS TO SEARCH: \n'), request_params, end='\n\n')

        response = FilmListRequester(params=request_params).perform(page=1)

        total_pages: int = response.json().get('totalPages')
        print(f'{total_pages=}')

        _current_page: int = 1

        while films_list := response.json().get('items'):
            print('\n\n===========================================================\n')
            print(f'RESPONSE: page={_current_page}')
            print(response.json())

            self.film_list.extend(films_list)

            _current_page += 1
            response = FilmListRequester(params=request_params).perform(_current_page)

        return self.film_list


def aggregate_reviews_by_ids_list(film_ids: list, existing_reviews: Optional[list[int]] = None) -> Union[dict[str, dict], tuple[dict[str, dict], int]]:
    reviews: Dict[str, dict] = {}
    try:
        for i, film_id in enumerate(film_ids):
            try:
                if existing_reviews:
                    new_reviews = ReviewAggregator(film_id).perform(existing_reviews[i])
                else:
                    new_reviews = ReviewAggregator(film_id).perform()
            except Exception as e:
                print('Exception:', e, file=sys.stderr)
                continue
            reviews.update(new_reviews)
    except KeyboardInterrupt:
        print('Keyboard interrupt caught. Films returned.', file=sys.stderr)
        return reviews

    return reviews


class ReviewAggregator:
    def __init__(self, film_id: int, return_total_pages: bool = False):
        self.film_id = film_id
        self.total_pages = None
        self.return_total_pages = return_total_pages

    def perform(self, n_existing_reviews: int = None) -> Union[Dict, Tuple[Dict, int]]:
        requester = ReviewRequester()

        reviews: Dict[str, dict] = {}

        response = requester.perform(self.film_id, {'page': 1})
        json_response: dict = response.json()

        print(f'{json_response.get("total")} reviews available by new request')

        if n_existing_reviews is None or not n_existing_reviews:
            _current_page: int = 1
        else:
            print(f'{n_existing_reviews} reviews already exist')

            if json_response.get('total') > n_existing_reviews:
                _current_page: int = n_existing_reviews // REST_PAGE_SIZE + 1
            else:
                print(f'No new reviews for {self.film_id} film ({json_response.get("total")} <(=) '
                      f'{n_existing_reviews}).')
                return reviews

        response = requester.perform(self.film_id, {'page': _current_page})
        json_response: dict = response.json()

        self.total_pages: int = json_response.get('totalPages')
        print(f'\n\ntotal_pages={self.total_pages}')
        if self.total_pages is None:
            print(json_response)

        print('Current pages:')
        while review_items := json_response.get('items'):
            print(_current_page, end=' ')
            print(review_items, end='\n\n\n')
            for review in review_items:
                reviews[review.get('description')] = {}
                for field in review:
                    if field != 'description':
                        reviews[review.get('description')][field] = review.get(field)
                reviews[review.get('description')]['film_id'] = self.film_id
            _current_page += 1
            json_response = requester.perform(self.film_id, {'page': _current_page}).json()
        print()

        if self.return_total_pages:
            return reviews, self.total_pages
        return reviews



class TopAggregator:
    top250_best = 'TOP_250_BEST_FILMS'
    top100_popular = 'TOP_100_POPULAR_FILMS'
    top_await = 'TOP_AWAIT_FILMS'

    def __init__(self, top_type: str):
        self.film_list = []
        self.top_type = top_type

    def perform(self) -> List:
        requester = TopFilmsRequester()
        response = requester.perform(self.top_type, page=1)
        json_response: dict = response.json()

        total_pages: int = json_response.get('pagesCount')
        print(f'{total_pages=}')

        _current_page: int = 1

        while top_items := json_response.get('films'):
            print(_current_page, end=' ')

            self.film_list.extend(top_items)

            _current_page += 1
            json_response = requester.perform(self.top_type, page=_current_page).json()

        return self.film_list
