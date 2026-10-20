from datetime import datetime
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime, parse_date
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from .models import Meter, MeterMessage
from .serializers import (
    MeterListSerializer,
    MeterDetailSerializer,
    MeterMessageListSerializer,
    MeterMessageDetailSerializer,
)


class MeterViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Керування та перегляд інформації про лічильники електроенергії.
    Підтримує пошук за ідентифікатором, пагінацію, отримання картки приладу,
    двох останніх записів та збереженої історії вимірювань.
    """
    queryset = Meter.objects.all().annotate(messages_count=Count("messages"))
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MeterDetailSerializer
        return MeterListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        search_query = self.request.query_params.get("search", "").strip()
        if search_query:
            qs = qs.filter(
                Q(system_title__icontains=search_query)
                | Q(serial_number__icontains=search_query)
                | Q(model_name__icontains=search_query)
            )
        return qs.order_by("-last_seen_at")

    @extend_schema(
        summary="Список лічильників",
        description="Повертає пагінований список лічильників із можливістю пошуку за ідентифікатором або серійним номером.",
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Пошуковий запит (System Title, серійний номер або модель)"
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Картка лічильника",
        description="Повертає детальну інформацію про лічильник, включаючи два останні отримані записи."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Два останні записи лічильника",
        description="Повертає рівно два останні коректні записи вимірювань для вказаного лічильника.",
        responses={200: MeterMessageListSerializer(many=True)}
    )
    @action(detail=True, methods=["get"], url_path="latest")
    def latest(self, request, id=None):
        meter = self.get_object()
        latest_msgs = (
            MeterMessage.objects.filter(meter=meter, is_duplicate=False)
            .order_by("-received_at")[:2]
        )
        serializer = MeterMessageListSerializer(latest_msgs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Історія вимірювань лічильника",
        description="Повертає збережену історію повідомлень лічильника з фільтрацією за діапазоном дат і пагінацією.",
        parameters=[
            OpenApiParameter(
                name="from",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description="Початок періоду (ISO 8601, наприклад: 2026-01-01T00:00:00Z або 2026-01-01)"
            ),
            OpenApiParameter(
                name="to",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                description="Кінець періоду (ISO 8601, наприклад: 2026-01-31T23:59:59Z або 2026-01-31)"
            ),

        ],
        responses={200: MeterMessageListSerializer(many=True)}
    )
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, id=None):
        meter = self.get_object()
        qs = MeterMessage.objects.filter(meter=meter, is_duplicate=False)

        # Фільтрація за датами
        from_str = request.query_params.get("from")
        to_str = request.query_params.get("to")

        if from_str:
            dt_from = parse_datetime(from_str) or parse_date(from_str)
            if dt_from:
                if isinstance(dt_from, datetime):
                    qs = qs.filter(received_at__gte=dt_from)
                else:
                    qs = qs.filter(received_at__date__gte=dt_from)

        if to_str:
            dt_to = parse_datetime(to_str) or parse_date(to_str)
            if dt_to:
                if isinstance(dt_to, datetime):
                    qs = qs.filter(received_at__lte=dt_to)
                else:
                    qs = qs.filter(received_at__date__lte=dt_to)

        qs = qs.order_by("-received_at")
        serializer_class = MeterMessageDetailSerializer if request.query_params.get("include_values") == "true" else MeterMessageListSerializer
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = serializer_class(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = serializer_class(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MeterMessageViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet
):
    """
    Перегляд детальної інформації про повідомлення DLMS Push.
    """
    queryset = MeterMessage.objects.all().select_related("meter")
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MeterMessageDetailSerializer
        return MeterMessageListSerializer

    @extend_schema(
        summary="Деталі повідомлення",
        description="Повертає повні дані повідомлення, включаючи розібрані параметри (JSONB) та вихідний пакет у HEX."
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Список повідомлень",
        description="Повертає пагінований список усіх повідомлень у системі.",
        parameters=[
            OpenApiParameter(
                name="meter_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="ID лічильника для фільтрації"
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        meter_id = request.query_params.get("meter_id")
        if meter_id:
            self.queryset = self.queryset.filter(meter_id=meter_id)
        return super().list(request, *args, **kwargs)
