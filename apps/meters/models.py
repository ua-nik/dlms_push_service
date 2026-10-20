from django.db import models


class Meter(models.Model):
    """
    Модель лічильника електроенергії (серії NIK).
    Автоматично реєструється при першому надходженні валідного повідомлення.
    """
    system_title = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Ідентифікатор системи (System Title / Hex)",
        help_text="Унікальний 8-байтовий DLMS System Title у HEX-форматі (16 символів)"
    )
    serial_number = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Серійний номер"
    )
    model_name = models.CharField(
        max_length=64,
        default="NIK",
        verbose_name="Модель приладу"
    )
    first_seen_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Час першого повідомлення"
    )
    last_seen_at = models.DateTimeField(
        db_index=True,
        verbose_name="Час останнього повідомлення"
    )
    last_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="Остання IP-адреса джерела"
    )
    last_port = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Останній UDP-порт джерела"
    )
    last_invocation_counter = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Останній Invocation Counter"
    )
    extra_info = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Додаткові метадані"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Створено"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Оновлено"
    )

    class Meta:
        verbose_name = "Лічильник"
        verbose_name_plural = "Лічильники"
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.model_name} [{self.system_title}]"


class MeterMessage(models.Model):
    """
    Модель повідомлення DLMS Push від лічильника.
    Зберігає вихідний пакет, часові мітки, параметри в JSONB та прапорці правил зберігання.
    """
    meter = models.ForeignKey(
        Meter,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
        verbose_name="Лічильник"
    )
    received_at = models.DateTimeField(
        db_index=True,
        verbose_name="Час прийому сервером"
    )
    event_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Час події приладу"
    )
    invocation_counter = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Invocation Counter (DLMS)"
    )
    raw_payload_hex = models.TextField(
        verbose_name="Вихідний UDP-пакет (HEX)"
    )
    packet_digest = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        editable=False,
        verbose_name="SHA-256 пакета з лічильником кадрів",
    )
    parsed_payload = models.JSONField(
        default=dict,
        verbose_name="Розібрані параметри (JSONB)"
    )
    source_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="IP-адреса джерела"
    )
    source_port = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="UDP-порт джерела"
    )

    # Legacy fields retained for compatibility with existing databases.
    # No longer updated or exposed by the API; history is kept indefinitely.
    is_month_start_1 = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Контрольний запис 1-го числа"
    )
    is_month_start_2 = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Контрольний запис 2-го числа"
    )
    is_month_penultimate = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Контрольний запис передостаннього дня місяця"
    )
    is_latest_1 = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Останній запис"
    )
    is_latest_2 = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Передостанній запис"
    )
    is_duplicate = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Повторно доставлене повідомлення"
    )

    class Meta:
        verbose_name = "Повідомлення лічильника"
        verbose_name_plural = "Повідомлення лічильників"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["meter", "-received_at"], name="meter_recv_idx"),
            models.Index(fields=["meter", "-event_at"], name="meter_event_idx"),
            models.Index(fields=["meter", "invocation_counter"], name="meter_invoc_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["meter", "packet_digest"], name="meter_packet_digest_uniq"),
        ]

    def __str__(self):
        return f"Msg #{self.id} from {self.meter.system_title} at {self.received_at}"

    @property
    def is_control_record(self) -> bool:
        """Перевіряє, чи задовольняє запис хоча б одній умові збереження."""
        return (
            self.is_month_start_1
            or self.is_month_start_2
            or self.is_month_penultimate
            or self.is_latest_1
            or self.is_latest_2
        )


class DiagnosticMessage(models.Model):
    """
    Діагностичне сховище для пошкоджених або нерозпізнаних пакетів.
    Має обмеження за загальним обсягом (FIFO) та терміном зберігання.
    """
    received_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Час прийому"
    )
    source_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="IP джерела"
    )
    source_port = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Порт джерела"
    )
    raw_payload_hex = models.TextField(
        verbose_name="Нерозібраний пакет (HEX)"
    )
    error_reason = models.CharField(
        max_length=255,
        verbose_name="Причина помилки"
    )
    error_details = models.TextField(
        blank=True,
        verbose_name="Деталі помилки"
    )
    system_title_hint = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Можливий System Title"
    )

    class Meta:
        verbose_name = "Діагностичне повідомлення"
        verbose_name_plural = "Діагностичні повідомлення"
        ordering = ["-received_at"]

    def __str__(self):
        return f"Diagnostic #{self.id}: {self.error_reason} at {self.received_at}"
