# loan_plugin.py
import logging
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import path # Wichtig für setup_urls mit path()
from django.http import HttpResponse
from django.template.loader import render_to_string # Zum Rendern des Templates
from django.shortcuts import redirect # Optional, nach Aktion

# InvenTree imports
from plugin import InvenTreePlugin
from plugin.mixins import ActionMixin, UrlsMixin, NavigationMixin # Geändert!
from stock.models import StockItem
from users.models import check_user_role # Für Berechtigungen (Beispiel)

# Setup Logger
logger = logging.getLogger("inventree")

# --- Konstanten für Metadaten ---
METADATA_LOAN_USER_KEY = "loaned_to_user_id"
METADATA_LOAN_DUE_DATE_KEY = "loan_due_date"
DEFAULT_LOAN_DURATION_DAYS = 14

class LoanPlugin(InvenTreePlugin, ActionMixin, UrlsMixin, NavigationMixin): # Mixins geändert
    """
    A plugin to add simple loan functionality to StockItems via a dedicated page.
    """

    NAME = "LoanPlugin"
    SLUG = "loan" # Wird für URLs und Namensräume verwendet
    TITLE = "Stock Item Loan Management"
    DESCRIPTION = "Adds a dedicated page to loan and return stock items."
    VERSION = "0.3.0" # Version erhöht
    AUTHOR = "Your Name Here"

    # --- ActionMixin Konfiguration (bleibt gleich) ---
    ACTION_NAME = "manage_loan"
    ACTION_ARGS = {
        "stock_item_pk": {
             'type': 'integer',
             'label': 'Stock Item ID',
             'required': True,
        },
        "loan_action": {
            'type': 'string',
            'label': 'Loan Action',
            'required': True,
            'choices': [('loan', 'Loan Item'), ('return', 'Return Item')],
        },
    }

    # --- NavigationMixin Konfiguration ---
    # Fügt einen Link zum Hauptmenü hinzu
    NAVIGATION_TAB_NAME = "Loan Management" # Name der Haupt-Navigationsgruppe
    NAVIGATION_TAB_ICON = "fas fa-hand-holding-box"
    NAVIGATION = [
        {
            'name': 'Loanable Items', # Name des Links
            'link': 'plugin:loan:loan-list', # URL-Name (plugin:<SLUG>:<url_name>)
            'icon': 'fas fa-list',
        }
    ]

    # --- UrlsMixin Konfiguration ---
    def setup_urls(self):
        """
        Definiert die URL-Muster für dieses Plugin.
        """
        return [
            # Die URL für unsere dedizierte Ausleihseite
            path('loan-list/', self.view_loan_list, name='loan-list'),
            # Optional: Könnte für AJAX-Updates genutzt werden, aber wir nutzen die Action API
            # path('status/<int:pk>/', self.view_item_status, name='item-status'),
        ]

    # --- Django View Funktion für die Plugin-Seite ---
    def view_loan_list(self, request):
        """
        Rendert die HTML-Seite, die alle ausleihbaren Items anzeigt.
        """
        # Berechtigungsprüfung (Beispiel: Nur eingeloggte Benutzer)
        if not request.user.is_authenticated:
            return HttpResponse("Permission Denied", status=403)

        # Hole alle StockItems (oder filtere nach Bedarf, z.B. nur bestimmte Kategorien)
        # Für Performance bei vielen Items: Paginierung hinzufügen!
        items = StockItem.objects.filter(in_stock=True).select_related('part', 'location') # Performance: Verwandte Objekte mitladen
        items_data = []

        for item in items:
            items_data.append({
                'item': item,
                'loan_status': self.get_loan_status(item)
            })

        # Rendere das Template mit den Daten
        context = {
            'plugin': self, # Übergibt das Plugin-Objekt an das Template
            'items': items_data,
            'requesting_user_pk': request.user.pk,
            # Beispiel: Übergebe Berechtigung an Template (kann auch im JS geprüft werden)
            'can_manage_stock': request.user.is_staff or request.user.has_perm('stock.change_stockitem')
        }
        # Wichtig: Der Template-Pfad muss für Django auffindbar sein!
        html = render_to_string('loan/loan_list.html', context, request=request)
        return HttpResponse(html)


    # --- Hilfsfunktionen (bleiben größtenteils gleich) ---
    def get_loan_status(self, item: StockItem):
        """Gibt den aktuellen Leihstatus des Items zurück."""
        user_id = item.get_metadata(METADATA_LOAN_USER_KEY)
        due_date = item.get_metadata(METADATA_LOAN_DUE_DATE_KEY)
        user_info = None

        if user_id:
            try:
                user = User.objects.get(pk=user_id)
                user_info = {
                    'pk': user.pk,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            except User.DoesNotExist:
                logger.warning(f"Loaned user with ID {user_id} not found for StockItem {item.pk}")
                item.delete_metadata(METADATA_LOAN_USER_KEY)
                item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
                user_id = None
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
        # Wichtig für Action API: Gib Status für JS-Update zurück
        return {"success": True, "message": f"Item loaned to {user.username} until {due_date.isoformat()}", "loan_status": self.get_loan_status(item)}

    def perform_return(self, item: StockItem, requesting_user: User):
        """Gibt das Item zurück."""
        loaned_user_id = item.get_metadata(METADATA_LOAN_USER_KEY)
        if not loaned_user_id:
            raise ValidationError(f"Item '{item}' is not currently loaned out.")

        if not (requesting_user.pk == loaned_user_id or requesting_user.is_staff):
             raise ValidationError("You do not have permission to return this item.")

        item.delete_metadata(METADATA_LOAN_USER_KEY)
        item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
        item.save()
        logger.info(f"StockItem {item.pk} returned by user {requesting_user.pk}")
        # Wichtig für Action API: Gib Status für JS-Update zurück
        return {"success": True, "message": "Item returned successfully.", "loan_status": self.get_loan_status(item)}


    # --- ActionMixin Implementierung (bleibt gleich) ---
    def perform_action(self, user: User, data=None):
        """
        Führt die 'manage_loan' Aktion aus.
        """
        stock_item_pk = data.get('stock_item_pk', None)
        loan_action = data.get('loan_action', None)
        result = {}

        if not stock_item_pk or not loan_action:
            raise ValidationError("Missing required arguments: stock_item_pk and loan_action")

        try:
            item = StockItem.objects.get(pk=stock_item_pk)

            if loan_action == 'loan':
                target_user = user
                result = self.perform_loan(item, target_user)

            elif loan_action == 'return':
                result = self.perform_return(item, user)

            else:
                raise ValidationError(f"Invalid loan_action: {loan_action}")

        except StockItem.DoesNotExist:
            raise ValidationError(f"StockItem with pk={stock_item_pk} not found.")
        except User.DoesNotExist:
            raise ValidationError(f"Target user not found.")
        except ValidationError as e:
            raise e
        except Exception as e:
            logger.error(f"Error in manage_loan action: {e}")
            raise ValidationError(f"An unexpected error occurred: {e}")

        # Stelle sicher, dass das Ergebnis für die Action API geeignet ist
        # Füge standardmäßig success=False hinzu, falls nicht gesetzt
        if 'success' not in result:
            result['success'] = False
        if 'message' not in result and not result['success']:
             result['message'] = "Action failed." # Standardfehlermeldung

        return result # Wird als JSON von der Action API zurückgegeben