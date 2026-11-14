// drei's <Html> removes its overlay div on unmount after the canvas wrapper may already have dropped it,
// which throws NotFoundError (seen when the Tracer replaces the replay). Skipping a removal of a node that
// is no longer a child is harmless, so tolerate it.
const orig = Node.prototype.removeChild
Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
  if (child.parentNode !== this) return child
  return orig.call(this, child) as T
}
