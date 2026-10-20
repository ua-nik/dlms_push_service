from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """
    Стандартна пагінація для списку лічильників та історії повідомлень.
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000
