from difflib import get_close_matches
from typing import List, Optional


def suggest_verb(
        input_verb: str,
        known_verbs: List[str],
        cutoff: float = 0.6,
        max_suggestions: int = 3
) -> List[str]:
    if not input_verb or not known_verbs:
        return []
    
    normalized_input = input_verb.lower().strip()
    lowercase_verbs = [v.lower() for v in known_verbs]

    matches = get_close_matches(
        normalized_input,
        lowercase_verbs,
        n=max_suggestions,
        cutoff=cutoff
    )

    if not matches:
        normalized_input_no_spaces = normalized_input.replace(" ", "")
        if normalized_input_no_spaces != normalized_input:
            no_space_verbs = [v.replace(" ", "") for v in lowercase_verbs]
            space_matches = get_close_matches(
                normalized_input_no_spaces,
                no_space_verbs,
                n=max_suggestions,
                cutoff=cutoff
            )
            for sm in space_matches:
                for orig, lower in zip(known_verbs, lowercase_verbs):
                    if lower.replace(" ", "") == sm and orig not in matches:
                        matches.append(orig)

                        
