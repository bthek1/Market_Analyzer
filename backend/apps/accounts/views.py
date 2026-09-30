from typing import ClassVar

from rest_framework import generics, permissions

from .serializers import UserSerializer


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
