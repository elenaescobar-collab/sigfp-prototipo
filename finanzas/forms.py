"""Formularios de captura. La validación se realiza con los validadores del
modelo, de modo que la regla de monto positivo se aplica en el servidor y no
solo en el navegador."""

from django import forms

from .models import Categoria, Movimiento


class MovimientoForm(forms.ModelForm):
    sentido = forms.ChoiceField(
        choices=[(Categoria.TIPO_EGRESO, "Egreso"), (Categoria.TIPO_INGRESO, "Ingreso")],
        initial=Categoria.TIPO_EGRESO,
        help_text="Se usa solo si no eliges categoría y ninguna regla la determina.",
    )

    class Meta:
        model = Movimiento
        fields = ["fecha", "descripcion", "monto", "categoria"]
        widgets = {"fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "— Automática —"
        self.fields["categoria"].queryset = Categoria.objects.filter(usuario=usuario, activa=True)
        self.fields["monto"].widget.attrs.update({"step": "0.01", "min": "0.01"})
        self.fields["descripcion"].widget.attrs.update({"placeholder": "Ej. Pago de luz CFE"})

    def clean_descripcion(self):
        d = self.cleaned_data["descripcion"].strip()
        if not d:
            raise forms.ValidationError("La descripción no puede quedar vacía.")
        return d
