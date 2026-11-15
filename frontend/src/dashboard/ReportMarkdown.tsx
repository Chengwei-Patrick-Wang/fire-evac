import Markdown from 'react-markdown'
import { AI_SUMMARY_HEADING, splitAiSummary } from '../model/aiSummary'

/**
 * A report card's markdown. When the card carries the "## AI summary (Claude)" section it is set apart: a heading, the model's text, and a small
 * "AI-written" note, so a reader can tell it from the numbers. A card without the section is rendered exactly as plain markdown.
 * The heading is an h4 in the Report tab and an h3 in the printed report, where the card's own headings are one level up.
 */
export default function ReportMarkdown({ md, print = false }: { md: string; print?: boolean }) {
  const parts = splitAiSummary(md)
  if (!parts) return <Markdown>{md}</Markdown>
  const Heading = print ? 'h3' : 'h4'
  return (
    <>
      {parts.before.trim() !== '' && <Markdown>{parts.before}</Markdown>}
      <div className="aisummary">
        <Heading>{AI_SUMMARY_HEADING}</Heading>
        <Markdown>{parts.body}</Markdown>
        <p className="aisummary-note dim">
          <span className="badge ai">AI-written</span> Claude wrote this from the numbers in this card. Check it against them.
        </p>
      </div>
      {parts.after.trim() !== '' && <Markdown>{parts.after}</Markdown>}
    </>
  )
}
