"""Summarize correspondence quality independently of technical job completion."""


_ACTIONS = frozenset({'WORD_START', 'NEXT_SYLLABLE', 'CONTINUE', 'TEXT_FRAGMENT', 'UNASSIGNED_ORIGINAL'})
_REVIEWS = frozenset({'AUTO_CANDIDATE', 'NEEDS_REVIEW', 'USER_CONFIRMED'})


def _risk(value):
    if isinstance(value, bool):
        return value
    if value == 'True':
        return True
    if value == 'False':
        return False
    return None


def summarize_quality(rows, lyrics):
    """Do not infer historical ownership or confirmation from lyric strings."""
    known = bool(rows) and all(
        row.get('placement_policy') == 'word_note_groups_v1'
        and row.get('placement_action') in _ACTIONS
        and row.get('review_status') in _REVIEWS
        and _risk(row.get('symbol_risk')) is not None for row in rows)
    if not known:
        return dict(quality_known=False, unresolved_notes=None, review_required_notes=None,
                    confirmed_notes=None, symbol_risks=None, placement_complete=None)
    unresolved = sum(row['placement_action'] == 'UNASSIGNED_ORIGINAL' for row in rows)
    review = sum(row['placement_action'] != 'UNASSIGNED_ORIGINAL'
                 and row['review_status'] == 'NEEDS_REVIEW' for row in rows)
    confirmed = sum(row['review_status'] == 'USER_CONFIRMED' for row in rows)
    risks = sum(_risk(row['symbol_risk']) for row in rows)
    missing = any(not row.get('note_numbers') for row in lyrics)
    return dict(quality_known=True, unresolved_notes=unresolved, review_required_notes=review,
                confirmed_notes=confirmed, symbol_risks=risks,
                placement_complete=not unresolved and not missing and not risks)
