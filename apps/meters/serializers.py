from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from .models import Meter, MeterMessage


class MeterMessageListSerializer(serializers.ModelSerializer):
    """
    Коротка інформація про повідомлення лічильника для списків та історії.
    """
    system_title = serializers.CharField(source="meter.system_title", read_only=True)

    class Meta:
        model = MeterMessage
        fields = [
            "id",
            "meter",
            "system_title",
            "received_at",
            "event_at",
            "invocation_counter",
            "is_duplicate",
        ]


class MeterMessageDetailSerializer(serializers.ModelSerializer):
    """
    Повні деталі повідомлення лічильника, включаючи розібрані параметри (JSONB)
    та вихідний шістнадцятковий пакет.
    Секрети та ключі шифрування в API ніколи не віддаються!
    """
    system_title = serializers.CharField(source="meter.system_title", read_only=True)

    class Meta:
        model = MeterMessage
        fields = [
            "id",
            "meter",
            "system_title",
            "received_at",
            "event_at",
            "invocation_counter",
            "source_ip",
            "source_port",
            "raw_payload_hex",
            "parsed_payload",
            "is_duplicate",
        ]


class MeterListSerializer(serializers.ModelSerializer):
    """
    Серіалізатор списку лічильників з пошуком та пагінацією.
    """
    messages_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Meter
        fields = [
            "id",
            "system_title",
            "serial_number",
            "model_name",
            "first_seen_at",
            "last_seen_at",
            "last_ip",
            "last_port",
            "messages_count",
        ]


class MeterDetailSerializer(serializers.ModelSerializer):
    """
    Картка лічильника з метаданими та двома останніми записами.
    """
    latest_records = serializers.SerializerMethodField()
    messages_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Meter
        fields = [
            "id",
            "system_title",
            "serial_number",
            "model_name",
            "first_seen_at",
            "last_seen_at",
            "last_ip",
            "last_port",
            "last_invocation_counter",
            "extra_info",
            "messages_count",
            "latest_records",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(MeterMessageListSerializer(many=True))
    def get_latest_records(self, obj):
        latest_msgs = obj.messages.filter(is_duplicate=False).order_by("-received_at")[:2]
        return MeterMessageListSerializer(latest_msgs, many=True).data
