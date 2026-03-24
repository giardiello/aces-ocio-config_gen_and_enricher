"""Topological sort and dependency expansion for vendor families."""
from graphlib import TopologicalSorter


def expand_dependencies(
    requested: set[str],
    depends_on: dict[str, list[str]],
) -> set[str]:
    """Expand requested families to include all transitive dependencies."""
    expanded = set(requested)
    stack = list(requested)
    while stack:
        name = stack.pop()
        for dep in depends_on.get(name, []):
            if dep not in expanded:
                expanded.add(dep)
                stack.append(dep)
    return expanded


def resolve_processing_order(
    families: set[str],
    depends_on: dict[str, list[str]],
) -> list[str]:
    """Return families in dependency-respecting, alphabetically-stable order."""
    ts = TopologicalSorter()
    for name in sorted(families):
        deps = [d for d in depends_on.get(name, []) if d in families]
        ts.add(name, *deps)
    ts.prepare()
    order: list[str] = []
    while ts.is_active():
        batch = sorted(ts.get_ready())
        order.extend(batch)
        ts.done(*batch)
    return order
