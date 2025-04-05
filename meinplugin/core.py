# loan_plugin.py
import logging
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from plugin import InvenTreePlugin
from plugin.mixins import ActionMixin, SettingsMixin, EventMixin, LocateMixin, PanelMixin, UrlsMixin, AppMixin, NavigationMixin, LabelPrintingMixin, BarcodeMixin, APICallMixin, ScheduleMixin, ReportMixin, ValidationMixin, CurrencyExchangeMixin, IconPackMixin, UserInterfaceMixin
from stock.models import StockItem
from inventree.api.serializers import UserSerializer

# Setup Logger
logger = logging.getLogger("inventree")

# --- Konstanten für Metadaten ---
METADATA_LOAN_USER_KEY = "loaned_to_user_id"
METADATA_LOAN_DUE_DATE_KEY = "loan_due_date"
DEFAULT_LOAN_DURATION_DAYS = 14

class LoanPlugin(InvenTreePlugin, ActionMixin, UserInterfaceMixin):
    """
    A plugin to add simple loan functionality to StockItems.
    """

    NAME = "LoanPlugin"
    SLUG = "loan"
    TITLE = "Stock Item Loan Management"
    DESCRIPTION = "Adds actions and UI elements to loan and return stock items."
    VERSION = "0.2.0"
    AUTHOR = "Your Name Here"

    # --- ActionMixin Konfiguration ---
    # Wir verwenden eine einzige Aktion und unterscheiden über die Daten
    ACTION_NAME = "manage_loan"
    ACTION_ARGS = {
        "stock_item_pk": {
             'type': 'integer',
             'label': 'Stock Item ID',
             'required': True,
             'help_text': 'Primary key of the stock item to manage',
        },
        "loan_action": {
            'type': 'string',
            'label': 'Loan Action',
            'required': True,
            'choices': [('loan', 'Loan Item'), ('return', 'Return Item')],
            'help_text': 'Specify whether to loan or return the item',
        },
        # Optional: Könnte für Admin-Override genutzt werden
        # "target_user_pk": {
        #     'type': 'integer',
        #     'label': 'Target User ID',
        #     'required': False,
        #     'help_text': 'Specify the user to loan to (optional, requires permission)',
        # }
    }

    # --- UserInterfaceMixin Methoden ---
    def get_ui_panels(self, request, context):
        """
        Inject custom panels into the InvenTree web interface.
        """
        panels = []

        # Nur auf der StockItem Detailseite anzeigen
        view = context.get('view', None)
        if view and view.view_name == 'stock_item_detail':
            try:
                item_id = int(context.get('pk', None))
                item = StockItem.objects.get(pk=item_id)

                # Hole aktuelle Leihinformationen
                loan_info = self.get_loan_status(item)

                panels.append({
                    'key': 'loan-panel',
                    'title': 'Loan Information',
                    'icon': 'fas fa-hand-holding-box',
                    'content': None, # Wird vom Frontend gerendert
                    'javascript_file': '/static/plugins/loan/loan_panel.js', # Pfad zur JS-Datei
                    'javascript_function': 'renderLoanPanel', # Name der JS-Funktion
                    'context': {
                        'stock_item_pk': item.pk,
                        'initial_loan_status': loan_info,
                        'requesting_user_pk': request.user.pk,
                        'can_manage_stock': request.user.is_staff or request.user.has_perm('stock.change_stockitem') # Beispiel-Berechtigung
                    }
                })
            except Exception as e:
                logger.error(f"Error injecting loan panel: {e}")

        return panels


    # --- Hilfsfunktionen ---
    def get_loan_status(self, item: StockItem):
        """Gibt den aktuellen Leihstatus des Items zurück."""
        user_id = item.get_metadata(METADATA_LOAN_USER_KEY)
        due_date = item.get_metadata(METADATA_LOAN_DUE_DATE_KEY)
        user_info = None

        if user_id:
            try:
                user = User.objects.get(pk=user_id)
                # Wichtig: Sensible Daten (wie E-Mail) nicht unnötig exposen!
                user_info = {
                    'pk': user.pk,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            except User.DoesNotExist:
                logger.warning(f"Loaned user with ID {user_id} not found for StockItem {item.pk}")
                # Bereinige ungültige Metadaten?
                item.delete_metadata(METADATA_LOAN_USER_KEY)
                item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
                user_id = None # Setze zurück, damit Status korrekt ist
                due_date = None

        return {
            'is_loaned': user_id is not None,
            'loaned_to': user_info,
            'due_date': due_date,
        }

    def perform_loan(self, item: StockItem, user: User):
        """Leiht das Item an den angegebenen User aus."""
        if item.get_metadata(METADATA_LOAN_USER_KEY):
            raise ValidationError(f"Item '{item}' is already loaned out.")

        due_date = date.today() + timedelta(days=DEFAULT_LOAN_DURATION_DAYS)
        item.set_metadata(METADATA_LOAN_USER_KEY, user.pk, change_tracked=True)
        item.set_metadata(METADATA_LOAN_DUE_DATE_KEY, due_date.isoformat(), change_tracked=True)
        item.save()
        logger.info(f"StockItem {item.pk} loaned to user {user.pk} until {due_date.isoformat()}")
        return {"success": True, "message": f"Item loaned to {user.username} until {due_date.isoformat()}", "loan_status": self.get_loan_status(item)}

    def perform_return(self, item: StockItem, requesting_user: User):
        """Gibt das Item zurück."""
        loaned_user_id = item.get_metadata(METADATA_LOAN_USER_KEY)
        if not loaned_user_id:
            raise ValidationError(f"Item '{item}' is not currently loaned out.")

        # Berechtigungsprüfung: Nur der Ausleihende oder Staff darf zurückgeben
        if not (requesting_user.pk == loaned_user_id or requesting_user.is_staff):
             raise ValidationError("You do not have permission to return this item.")

        item.delete_metadata(METADATA_LOAN_USER_KEY)
        item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
        item.save()
        logger.info(f"StockItem {item.pk} returned by user {requesting_user.pk}")
        return {"success": True, "message": "Item returned successfully.", "loan_status": self.get_loan_status(item)}


    # --- ActionMixin Implementierung ---
    def perform_action(self, user: User, data=None):
        """
        Führt die 'manage_loan' Aktion aus.
        Unterscheidet zwischen 'loan' und 'return' basierend auf 'data'.
        """
        stock_item_pk = data.get('stock_item_pk', None)
        loan_action = data.get('loan_action', None)
        result = {} # Das wird an das Frontend zurückgegeben

        if not stock_item_pk or not loan_action:
            raise ValidationError("Missing required arguments: stock_item_pk and loan_action")

        try:
            item = StockItem.objects.get(pk=stock_item_pk)

            if loan_action == 'loan':
                # Wer leiht aus? Standardmäßig der anfragende User
                # target_user_pk = data.get('target_user_pk', user.pk) # Für Admin-Override
                target_user = user # Vereinfacht: Nur an sich selbst ausleihen
                result = self.perform_loan(item, target_user)

            elif loan_action == 'return':
                result = self.perform_return(item, user)

            else:
                raise ValidationError(f"Invalid loan_action: {loan_action}")

        except StockItem.DoesNotExist:
            raise ValidationError(f"StockItem with pk={stock_item_pk} not found.")
        except User.DoesNotExist:
            # Relevant, wenn target_user_pk verwendet wird
            raise ValidationError(f"Target user not found.")
        except ValidationError as e:
            # Bestehende Validierungsfehler weitergeben
            raise e
        except Exception as e:
            logger.error(f"Error in manage_loan action: {e}")
            raise ValidationError(f"An unexpected error occurred: {e}")

        return result

    # Optional: get_info & get_result können angepasst werden, aber für den Start nicht nötig
    # def get_info(self, user, data=None):
    #    return {"info": "Manages loan status for a stock item."}

    # def get_result(self, user, data=None, result=None):
    #    return result # Gibt das Ergebnis von perform_action zurück