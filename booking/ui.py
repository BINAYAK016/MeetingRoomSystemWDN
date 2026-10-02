from django.core.paginator import Paginator


def paginate(request, queryset, per_page=25):
    """Keep filters while paging through complete result sets."""
    page = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return {"page_obj": page, "page_query": params.urlencode()}
