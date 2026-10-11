"""Translate saved task UI labels at display time, without modifying history."""
import re

_LABELS = {
    'Przerwano': 'Interrupted', 'Przekroczono limit czasu': 'Time limit exceeded',
    'Oczekiwanie w kolejce...': 'Waiting in queue...', 'Rozpoczynanie generowania...': 'Starting generation...',
    'Zakończono pomyślnie': 'Completed successfully', 'Szkic gotowy do przeglądu': 'Draft ready for review',
    'Analiza wymaga przeglądu': 'Analysis requires review', 'Przygotowywanie wyników...': 'Preparing results...',
    'Błąd uwierzytelniania': 'Authentication failed', 'Błąd generowania AI': 'AI generation failed',
    'Nieoczekiwany błąd': 'Unexpected error', 'Analiza oferty...': 'Analyzing the job...',
    'Generowanie CV...': 'Generating the resume...',
}


def ui_text(value):
    if not value:
        return ''
    if value in _LABELS:
        return _LABELS[value]
    # Old technical task errors may include Polish provider messages. Retain the
    # saved message on disk, but avoid mixed-language errors in the interface.
    if re.search(r'[ąćęłńóśźż]|\b(?:Nie|Przetwarzanie|Generowanie|Oczekiwanie|Analizowanie|Walidacja|Zadanie|Testowanie|Rozpoczynanie)\b', value):
        return 'Saved task message — review the original task record for details.'
    return value
