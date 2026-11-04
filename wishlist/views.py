from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product
from .models import WishlistItem
from .serializers import WishlistItemSerializer


class WishlistListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Return the authenticated customer's wishlist.
        """

        wishlist = (
            WishlistItem.objects
            .filter(user=request.user)
            .select_related("product")
        )

        serializer = WishlistItemSerializer(
            wishlist,
            many=True,
            context={"request": request},
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        Add a product to the authenticated customer's wishlist.

        Expected body:
        {
            "product_id": 1
        }
        """

        product_id = request.data.get("product_id")

        if not product_id:
            return Response(
                {"detail": "product_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product = get_object_or_404(Product, pk=product_id)

        # get_or_create makes adding the same product idempotent.
        wishlist_item, created = WishlistItem.objects.get_or_create(
            user=request.user,
            product=product,
        )

        serializer = WishlistItemSerializer(
            wishlist_item,
            context={"request": request},
        )

        return Response(
            serializer.data,
            status=(
                status.HTTP_201_CREATED
                if created
                else status.HTTP_200_OK
            ),
        )


class WishlistItemDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        """
        Delete an item only if it belongs to the authenticated customer.
        """

        wishlist_item = get_object_or_404(
            WishlistItem,
            pk=item_id,
            user=request.user,
        )

        wishlist_item.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)