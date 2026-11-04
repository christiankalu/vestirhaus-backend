from django.urls import path

from .views import (
    WishlistListCreateView,
    WishlistItemDeleteView,
)

urlpatterns = [
    path(
        "wishlist/",
        WishlistListCreateView.as_view(),
        name="wishlist-list-create",
    ),

    path(
        "wishlist/items/<int:item_id>/",
        WishlistItemDeleteView.as_view(),
        name="wishlist-item-delete",
    ),
]