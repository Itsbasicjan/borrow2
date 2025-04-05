# core.py (in deinem meinplugin Verzeichnis)

import logging
from datetime import date, timedelta

# Django Imports
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import path # Wichtig für setup_urls mit path()
from django.http import HttpResponse
from django.template.loader import render_to_string # Zum Rendern des Templates
from django.shortcuts import redirect # Optional, nach Aktion

# InvenTree Imports
from plugin import InvenTreePlugin
from plugin.mixins import ActionMixin, UrlsMixin, NavigationMixin # Angepasst für dedizierte Seite
from stock.models import StockItem
# from users.models import check_user_role # Beispiel für Berechtigungsprüfung, falls benötigt

# Setup Logger
# Es ist besser, einen spezifischen Logger für dein Plugin zu verwenden
logger = logging.getLogger(f"inventree.plugin.meinplugin") # Angepasster Logger-Name

# --- Konstanten für Metadaten ---
METADATA_LOAN_USER_KEY = "loaned_to_user_id"
METADATA_LOAN_DUE_DATE_KEY = "loan_due_date"
DEFAULT_LOAN_DURATION_DAYS = 14 # Beispielwert

class LoanPlugin(InvenTreePlugin, ActionMixin, UrlsMixin, NavigationMixin):
    """
    A plugin to add simple loan functionality to StockItems via a dedicated page.
    Located in core.py for the 'meinplugin' package.
    """

    NAME = "LoanPlugin" # Der interne Name des Plugins
    SLUG = "loan" # Wichtig: Wird für URLs und Template-Pfade verwendet!
    TITLE = "Stock Item Loan Management" # Angezeigter Name im Menü/Admin
    DESCRIPTION = "Adds a dedicated page to loan and return stock items."
    VERSION = "0.3.1" # Version erhöht
    AUTHOR = "Your Name Here"

    # --- ActionMixin Konfiguration ---
    # Definiert die API-Aktion, die vom Frontend aufgerufen wird
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
    }

    # --- NavigationMixin Konfiguration ---
    # Fügt einen Link zum Hauptmenü (Sidebar) hinzu
    NAVIGATION_TAB_NAME = "Loan Management" # Name der Haupt-Navigationsgruppe
    NAVIGATION_TAB_ICON = "fas fa-hand-holding-box"
    NAVIGATION = [
        {
            'name': 'Loanable Items', # Angezeigter Name des Links
            'link': 'plugin:loan:loan-list', # URL-Name: 'plugin:<SLUG>:<url_name_aus_setup_urls>'
            'icon': 'fas fa-list',
        }
    ]

    # --- UrlsMixin Konfiguration ---
    def setup_urls(self):
        """
        Definiert die URL-Muster für dieses Plugin.
        Diese URLs werden unter /plugin/<SLUG>/ gemountet.
        """
        return [
            # Die URL für unsere dedizierte Ausleihseite
            # Der 'name' hier ('loan-list') wird im NAVIGATION link verwendet.
            path('loan-list/', self.view_loan_list, name='loan-list'),
        ]

    # --- Django View Funktion für die Plugin-Seite ---
    def view_loan_list(self, request):
        """
        Rendert die HTML-Seite, die alle ausleihbaren Items anzeigt.
        Wird aufgerufen, wenn /plugin/loan/loan-list/ besucht wird.
        """
        # Berechtigungsprüfung (Beispiel: Nur eingeloggte Benutzer)
        if not request.user.is_authenticated:
            # Alternativ: Login-Weiterleitung oder spezifischere Berechtigungen prüfen
            # from django.contrib.auth.decorators import login_required
            # @login_required
            # def view_loan_list(self, request): ...
            return HttpResponse("Permission Denied: You must be logged in.", status=403)

        # Hole alle StockItems, die im Lager sind (oder filtere weiter nach Bedarf)
        # Bei sehr vielen Items sollte hier Paginierung implementiert werden!
        items = StockItem.objects.filter(in_stock=True).select_related('part', 'location') # Performance: Verwandte Objekte mitladen

        items_data = []
        for item in items:
            items_data.append({
                'item': item,
                'loan_status': self.get_loan_status(item) # Hole Status für jedes Item
            })

        # Kontextdaten für das Template vorbereiten
        context = {
            'plugin': self, # Übergibt das Plugin-Objekt selbst (nützlich für Metadaten im Template)
            'items': items_data,
            'requesting_user_pk': request.user.pk,
            # Beispiel: Berechtigung für UI-Logik (Buttons aktivieren/deaktivieren)
            'can_manage_stock': request.user.is_staff or request.user.has_perm('stock.change_stockitem')
        }

        # Rendere das Template
        # Wichtig: Django muss das Template finden können!
        # Erwartet wird: <plugin_verzeichnis>/templates/<SLUG>/<template_name>.html
        # Also hier: meinplugin/templates/loan/loan_list.html
        try:
            html = render_to_string('loan/loan_list.html', context, request=request)
            return HttpResponse(html)
        except Exception as e:
            logger.error(f"Error rendering loan_list.html: {e}")
            # Gib einen hilfreichen Fehler zurück, falls das Template nicht gefunden wird etc.
            return HttpResponse(f"Error rendering plugin template: {e}", status=500)


    # --- Hilfsfunktionen ---
    def get_loan_status(self, item: StockItem):
        """Gibt den aktuellen Leihstatus des Items als Dictionary zurück."""
        user_id = item.get_metadata(METADATA_LOAN_USER_KEY)
        due_date = item.get_metadata(METADATA_LOAN_DUE_DATE_KEY)
        user_info = None

        if user_id:
            try:
                user = User.objects.get(pk=user_id)
                # Gib nur notwendige, unkritische User-Infos zurück
                user_info = {
                    'pk': user.pk,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            except User.DoesNotExist:
                logger.warning(f"Loaned user with ID {user_id} not found for StockItem {item.pk}. Clearing metadata.")
                # Bereinige ungültige Metadaten
                try:
                    item.delete_metadata(METADATA_LOAN_USER_KEY)
                    item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
                    # Speichern ist hier nicht nötig, da get_metadata nicht speichert
                except Exception as meta_e:
                     logger.error(f"Could not clear loan metadata for item {item.pk}: {meta_e}")
                user_id = None
                due_date = None

        return {
            'is_loaned': user_id is not None,
            'loaned_to': user_info, # Ist None, wenn nicht ausgeliehen oder User nicht gefunden
            'due_date': due_date,   # Ist None, wenn nicht ausgeliehen
        }

    def perform_loan(self, item: StockItem, user: User):
        """Führt die Ausleihe durch und gibt Ergebnis-Dict zurück."""
        if item.get_metadata(METADATA_LOAN_USER_KEY):
            raise ValidationError(f"Item '{item}' (PK: {item.pk}) is already loaned out.")

        # Berechne Fälligkeitsdatum
        due_date = date.today() + timedelta(days=DEFAULT_LOAN_DURATION_DAYS)

        # Setze Metadaten
        item.set_metadata(METADATA_LOAN_USER_KEY, user.pk, change_tracked=True, description="User ID who loaned the item")
        item.set_metadata(METADATA_LOAN_DUE_DATE_KEY, due_date.isoformat(), change_tracked=True, description="Loan due date")
        # set_metadata speichert automatisch, wenn change_tracked=True

        logger.info(f"StockItem {item.pk} loaned to user {user.username} (PK: {user.pk}) until {due_date.isoformat()}")

        # Gib Erfolg und aktuellen Status zurück (wichtig für Action API -> JS Update)
        return {"success": True, "message": f"Item loaned to {user.username} until {due_date.isoformat()}", "loan_status": self.get_loan_status(item)}

    def perform_return(self, item: StockItem, requesting_user: User):
        """Führt die Rückgabe durch und gibt Ergebnis-Dict zurück."""
        loaned_user_id = item.get_metadata(METADATA_LOAN_USER_KEY)

        if not loaned_user_id:
            raise ValidationError(f"Item '{item}' (PK: {item.pk}) is not currently loaned out.")

        # Berechtigungsprüfung: Nur der Ausleihende oder Staff darf zurückgeben
        if not (requesting_user.pk == loaned_user_id or requesting_user.is_staff):
             # Alternativ spezifischere Berechtigung prüfen
             # if not requesting_user.has_perm('stock.change_stockitem'):
             raise ValidationError("You do not have permission to return this item.")

        # Lösche Metadaten
        item.delete_metadata(METADATA_LOAN_USER_KEY)
        item.delete_metadata(METADATA_LOAN_DUE_DATE_KEY)
        # delete_metadata speichert automatisch

        logger.info(f"StockItem {item.pk} returned by user {requesting_user.username} (PK: {requesting_user.pk})")

        # Gib Erfolg und aktuellen Status zurück
        return {"success": True, "message": "Item returned successfully.", "loan_status": self.get_loan_status(item)}


    # --- ActionMixin Implementierung ---
    def perform_action(self, user: User, data=None):
        """
        Führt die 'manage_loan' API-Aktion aus.
        Wird vom Frontend (JavaScript) aufgerufen.
        'user' ist der eingeloggte User, der die Aktion auslöst.
        'data' enthält die an die API gesendeten Daten (hier: stock_item_pk, loan_action).
        """
        if data is None:
             data = {} # Sicherstellen, dass data ein Dict ist

        stock_item_pk = data.get('stock_item_pk', None)
        loan_action = data.get('loan_action', None)
        result = {} # Das Ergebnis-Dictionary für die API-Antwort

        # Grundlegende Validierung der Eingabedaten
        if not stock_item_pk or not isinstance(stock_item_pk, int):
            raise ValidationError("Missing or invalid required argument: 'stock_item_pk' (must be an integer)")
        if not loan_action or loan_action not in ['loan', 'return']:
             raise ValidationError("Missing or invalid required argument: 'loan_action' (must be 'loan' or 'return')")

        try:
            # Hole das betroffene StockItem
            item = StockItem.objects.get(pk=stock_item_pk)

            # Führe die entsprechende Aktion aus
            if loan_action == 'loan':
                # In dieser einfachen Version leiht der auslösende User an sich selbst aus
                target_user = user
                result = self.perform_loan(item, target_user)

            elif loan_action == 'return':
                # Der auslösende User versucht, das Item zurückzugeben
                result = self.perform_return(item, user)

            # Keine else benötigt wegen Validierung oben

        except StockItem.DoesNotExist:
            # Fehlermeldung für die API, wenn das Item nicht existiert
            logger.warning(f"manage_loan action failed: StockItem with pk={stock_item_pk} not found.")
            raise ValidationError(f"StockItem with pk={stock_item_pk} not found.")
        except ValidationError as e:
            # Fange spezifische Validierungsfehler aus perform_loan/perform_return ab
            logger.warning(f"manage_loan action validation error for item {stock_item_pk}: {e}")
            raise e # Gib den Fehler an die API weiter
        except Exception as e:
            # Fange unerwartete Fehler ab
            logger.error(f"Unexpected error in manage_loan action for item {stock_item_pk}: {e}", exc_info=True) # Logge den Traceback
            # Gib eine generische Fehlermeldung an die API
            raise ValidationError(f"An unexpected server error occurred: {e}")

        # Stelle sicher, dass das Ergebnis-Dictionary für die API-Antwort geeignet ist
        if 'success' not in result:
            result['success'] = False # Standardmäßig fehlschlagen, wenn nicht explizit auf True gesetzt
        if not result['success'] and 'message' not in result:
             result['message'] = "Loan action failed." # Füge Standardfehlermeldung hinzu

        return result # Dieses Dictionary wird als JSON-Antwort von der /api/action/ zurückgegeben