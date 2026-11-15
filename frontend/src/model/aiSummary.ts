/** The heading of the section a report card begins with when the model wrote a summary of it (3 to 4 sentences). Template cards have none. */
export const AI_SUMMARY_HEADING = 'AI summary (Claude)'

export interface AiSummaryParts {
  /** the markdown above the section (empty when the card begins with it) */
  before: string
  /** the section's text, without its heading */
  body: string
  /** the markdown below it: the section ends at the next heading or rule */
  after: string
}

const HEADING = /^ {0,3}#{2,3}[ \t]+AI summary \(Claude\)[ \t]*#*[ \t]*$/i
const NEXT = /^ {0,3}(#{1,6}[ \t]|(-{3,}|\*{3,}|_{3,})[ \t]*$)/

/**
 * Splits the "## AI summary (Claude)" section out of a report card's markdown, or returns null when the card has none (every template
 * card) or the heading has nothing under it, so the card is then shown exactly as it is.
 */
export function splitAiSummary(md: string): AiSummaryParts | null {
  const lines = md.split(/\r?\n/)
  const at = lines.findIndex((l) => HEADING.test(l))
  if (at < 0) return null
  let end = lines.length
  for (let i = at + 1; i < lines.length; i++) {
    if (NEXT.test(lines[i])) {
      end = i
      break
    }
  }
  const body = lines.slice(at + 1, end).join('\n').trim()
  if (!body) return null
  return { before: lines.slice(0, at).join('\n'), body, after: lines.slice(end).join('\n') }
}
