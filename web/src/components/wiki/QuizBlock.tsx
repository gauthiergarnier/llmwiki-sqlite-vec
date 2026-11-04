'use client'

import * as React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Check, ChevronLeft, ChevronRight, Lightbulb, ListChecks, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiFetch, isApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useUserStore } from '@/stores'
import { parseQuizYaml } from '@/lib/quiz/parseQuiz'
import { questionKey } from '@/lib/quiz/questionKey'
import { queueCompletedSave, recordCompleted, seedCompleted } from '@/lib/quiz/quizProgress'
import type { ChoiceQuestion, QuizGradeResult, QuizQuestion, QuizSpec, TextQuestion } from '@/lib/quiz/types'
import type { DocumentListItem } from '@/lib/types'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

const QUIZ_REMARK = [remarkGfm, remarkMath]
const QUIZ_REHYPE = [rehypeKatex]

interface QuizBlockProps {
  source: string
  documentId: string | null
  documentsRef: React.RefObject<DocumentListItem[] | undefined>
}

export function QuizBlock({ source, documentId, documentsRef }: QuizBlockProps) {
  const parsed = React.useMemo(() => parseQuizYaml(source), [source])
  if (!parsed.spec) {
    return (
      <div className="my-3">
        <pre className="text-[13px] leading-relaxed bg-muted/60 border border-border rounded-lg p-4 overflow-x-auto">
          {source}
        </pre>
        <p role="alert" className="mt-1 text-xs text-muted-foreground/70">
          Quiz unavailable. Use YAML with a non-empty <code>questions</code> list. Each question needs a{' '}
          <code>prompt</code> plus either <code>options</code> and a zero-based <code>answer</code>, or{' '}
          <code>type: text</code> and a <code>rubric</code>.
        </p>
      </div>
    )
  }
  return (
    <QuizCard
      key={`${documentId ?? 'unpersisted'}:${source}`}
      source={source}
      spec={parsed.spec}
      documentId={documentId}
      documentsRef={documentsRef}
    />
  )
}

function QuizCard({
  source,
  spec,
  documentId,
  documentsRef,
}: {
  source: string
  spec: QuizSpec
  documentId: string | null
  documentsRef: React.RefObject<DocumentListItem[] | undefined>
}) {
  const token = useUserStore((s) => s.accessToken)
  const questionKeys = React.useMemo(
    () => spec.questions.map((question, index) => questionKey(source, question, index)),
    [source, spec.questions],
  )
  const [completed, setCompleted] = React.useState<Set<string>>(() => {
    if (!documentId) return new Set()
    return new Set(seedCompleted(documentId, storedQuizKeys(documentsRef.current, documentId)))
  })
  const [activeIndex, setActiveIndex] = React.useState(() => {
    if (!documentId) return 0
    const saved = seedCompleted(documentId, storedQuizKeys(documentsRef.current, documentId))
    const firstIncomplete = questionKeys.findIndex((key) => !saved.has(key))
    return firstIncomplete === -1 ? questionKeys.length - 1 : firstIncomplete
  })

  const handleComplete = React.useCallback(
    (key: string) => {
      setCompleted((prev) => new Set(prev).add(key))
      if (!documentId) return
      recordCompleted(documentId, key)
      if (!isLocal && !token) return
      queueCompletedSave(documentId, (keys) =>
        apiFetch(`/v1/documents/${documentId}`, token ?? '', {
          method: 'PATCH',
          body: JSON.stringify({ metadata: { quiz: keys } }),
        }),
      ).catch(() => {
        // Completion survives in session memory; the next completed answer re-sends the full set.
      })
    },
    [documentId, token],
  )

  const doneCount = questionKeys.filter((key) => completed.has(key)).length
  const activeQuestion = spec.questions[activeIndex]
  const activeKey = questionKeys[activeIndex]
  const activeComplete = completed.has(activeKey)
  const isFirst = activeIndex === 0
  const isLast = activeIndex === spec.questions.length - 1

  return (
    <div
      data-quiz-block
      data-wiki-highlighter
      className="my-5 overflow-hidden rounded-lg border border-border bg-muted/20"
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-border/60 bg-muted/40">
        <div className="flex items-center gap-2 min-w-0">
          <ListChecks className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden="true" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70 truncate">
            Quiz
          </span>
        </div>
        <span aria-live="polite" className="text-[11px] tabular-nums text-muted-foreground/60 shrink-0">
          Question {activeIndex + 1} of {spec.questions.length}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`${doneCount} of ${spec.questions.length} questions complete`}
        aria-valuemin={0}
        aria-valuemax={spec.questions.length}
        aria-valuenow={doneCount}
        className="h-px bg-border/40"
      >
        <div
          className="h-full bg-foreground/45 transition-[width] duration-200 motion-reduce:transition-none"
          style={{ width: `${(doneCount / spec.questions.length) * 100}%` }}
        />
      </div>
      <QuizQuestionItem
        key={`${activeKey}-${activeIndex}`}
        question={activeQuestion}
        isComplete={activeComplete}
        onComplete={() => handleComplete(activeKey)}
        isFirst={isFirst}
        isLast={isLast}
        onPrevious={() => setActiveIndex((index) => Math.max(0, index - 1))}
        onNext={() => setActiveIndex((index) => Math.min(spec.questions.length - 1, index + 1))}
      />
    </div>
  )
}

function QuizQuestionItem({
  question,
  isComplete,
  onComplete,
  isFirst,
  isLast,
  onPrevious,
  onNext,
}: {
  question: QuizQuestion
  isComplete: boolean
  onComplete: () => void
  isFirst: boolean
  isLast: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  if (question.kind === 'text') {
    return (
      <TextQuestionItem
        question={question}
        isComplete={isComplete}
        onComplete={onComplete}
        isFirst={isFirst}
        isLast={isLast}
        onPrevious={onPrevious}
        onNext={onNext}
      />
    )
  }
  return (
    <>
      <ChoiceQuestionItem question={question} isComplete={isComplete} onComplete={onComplete} />
      <QuizFooter
        isFirst={isFirst}
        isLast={isLast}
        isComplete={isComplete}
        onPrevious={onPrevious}
        onNext={onNext}
      />
    </>
  )
}

function ChoiceQuestionItem({
  question,
  isComplete,
  onComplete,
}: {
  question: ChoiceQuestion
  isComplete: boolean
  onComplete: () => void
}) {
  const [wrongPicks, setWrongPicks] = React.useState<Set<number>>(new Set())

  const handlePick = (index: number) => {
    if (isComplete) return
    if (index === question.answer) {
      onComplete()
      return
    }
    setWrongPicks((prev) => new Set(prev).add(index))
  }

  return (
    <div className="px-4 py-3.5">
      <QuizMarkdown text={question.prompt} className="font-medium text-foreground/95" />
      <div className="mt-2.5 space-y-1.5">
        {question.options.map((option, index) => {
          const isAnswer = index === question.answer
          const showCorrect = isComplete && isAnswer
          const showWrong = !isComplete && wrongPicks.has(index)
          return (
            <button
              key={index}
              type="button"
              disabled={isComplete}
              onClick={() => handlePick(index)}
              className={cn(
                'w-full flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors',
                showCorrect
                  ? 'border-emerald-500/50 bg-emerald-500/[0.08]'
                  : showWrong
                    ? 'border-destructive/40 bg-destructive/[0.06]'
                    : 'border-border/70 bg-background/60',
                !isComplete && !showWrong && 'hover:border-border hover:bg-accent/60 cursor-pointer',
                isComplete && !isAnswer && 'opacity-50',
              )}
            >
              <span className="mt-0.5 shrink-0">
                {showCorrect ? (
                  <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                ) : showWrong ? (
                  <X className="size-3.5 text-destructive" />
                ) : (
                  <span className="block size-3.5 rounded-full border border-muted-foreground/30" />
                )}
              </span>
              <QuizMarkdown text={option} className="min-w-0" />
            </button>
          )
        })}
      </div>
      {!isComplete && <QuizHints hints={question.hints} />}
      {isComplete && question.explanation && <QuizExplanation text={question.explanation} />}
    </div>
  )
}

function TextQuestionItem({
  question,
  isComplete,
  onComplete,
  isFirst,
  isLast,
  onPrevious,
  onNext,
}: {
  question: TextQuestion
  isComplete: boolean
  onComplete: () => void
  isFirst: boolean
  isLast: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  const token = useUserStore((s) => s.accessToken)
  const [answer, setAnswer] = React.useState('')
  const [grading, setGrading] = React.useState(false)
  const [result, setResult] = React.useState<QuizGradeResult | null>(null)
  const [gradeError, setGradeError] = React.useState<string | null>(null)
  const [selfCheck, setSelfCheck] = React.useState(isLocal)
  const [revealed, setRevealed] = React.useState(false)

  const trimmed = answer.trim()

  const handleCheck = async () => {
    if (!trimmed || grading || isComplete) return
    if (selfCheck) {
      setRevealed(true)
      return
    }
    setGrading(true)
    setGradeError(null)
    try {
      const graded = await apiFetch<QuizGradeResult>('/v1/quiz/grade', token ?? '', {
        method: 'POST',
        body: JSON.stringify({ prompt: question.prompt, rubric: question.rubric, answer: trimmed }),
      })
      setResult(graded)
      if (graded.verdict === 'correct') onComplete()
    } catch (err) {
      if (isApiError(err) && err.status === 501) {
        setSelfCheck(true)
        setRevealed(true)
      } else if (isApiError(err) && err.status === 429) {
        setGradeError(
          err.message.startsWith('Daily grading limit')
            ? err.message
            : 'Grading is temporarily limited. Try again shortly.',
        )
      } else {
        setGradeError('Grading failed. Try again.')
      }
    } finally {
      setGrading(false)
    }
  }

  return (
    <>
      <div className="px-4 py-3.5">
        <QuizMarkdown text={question.prompt} className="font-medium text-foreground/95" />
        <div className="mt-2.5">
          {isComplete && !trimmed ? (
            <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
              <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
              <span>Completed</span>
            </div>
          ) : (
            <Textarea
              value={answer}
              onChange={(e) => {
                setAnswer(e.target.value)
                setResult(null)
                setGradeError(null)
              }}
              disabled={isComplete || grading}
              aria-label="Your answer"
              placeholder="Type your answer…"
              className="min-h-20 bg-background/60 text-sm"
            />
          )}
          {gradeError && (
            <p role="status" aria-live="polite" className="mt-2 text-xs text-destructive">
              {gradeError}
            </p>
          )}
        </div>
        {result && <GradeFeedback verdict={result.verdict} feedback={result.feedback} />}
        {!isComplete && selfCheck && revealed && (
          <SelfCheckPanel
            question={question}
            onGotIt={onComplete}
            onKeepTrying={() => setRevealed(false)}
          />
        )}
        {!isComplete && <QuizHints hints={question.hints} />}
        {isComplete && question.explanation && <QuizExplanation text={question.explanation} />}
      </div>
      <QuizFooter
        isFirst={isFirst}
        isLast={isLast}
        isComplete={isComplete}
        onPrevious={onPrevious}
        onNext={onNext}
        onCheck={handleCheck}
        checkLabel={selfCheck ? 'Compare answer' : 'Check answer'}
        checkDisabled={!trimmed || grading}
        checking={grading}
        onAcceptResult={
          result && result.verdict !== 'correct'
            ? () => {
                onComplete()
                if (!isLast) onNext()
              }
            : undefined
        }
      />
    </>
  )
}

function QuizFooter({
  isFirst,
  isLast,
  isComplete,
  onPrevious,
  onNext,
  onCheck,
  onAcceptResult,
  checkLabel = 'Check answer',
  checkDisabled = false,
  checking = false,
}: {
  isFirst: boolean
  isLast: boolean
  isComplete: boolean
  onPrevious: () => void
  onNext: () => void
  onCheck?: () => void
  onAcceptResult?: () => void
  checkLabel?: string
  checkDisabled?: boolean
  checking?: boolean
}) {
  return (
    <div
      data-quiz-footer
      className="flex min-h-12 items-center justify-between gap-3 border-t border-border/50 px-3 py-2"
    >
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={isFirst || checking}
        onClick={onPrevious}
      >
        <ChevronLeft aria-hidden="true" />
        Previous
      </Button>
      {isLast && isComplete ? (
        <span className="flex items-center gap-1.5 px-2 text-xs font-medium text-foreground/75">
          <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
          Quiz complete
        </span>
      ) : isComplete ? (
        <Button type="button" size="sm" variant="outline" onClick={onNext}>
          Next question
          <ChevronRight aria-hidden="true" />
        </Button>
      ) : onAcceptResult ? (
        <Button type="button" size="sm" variant="outline" onClick={onAcceptResult}>
          {isLast ? 'Finish quiz' : 'Next question'}
          {isLast ? <Check aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
        </Button>
      ) : onCheck ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={checkDisabled}
          onClick={onCheck}
        >
          {checking && <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />}
          {checkLabel}
        </Button>
      ) : (
        <Button type="button" size="sm" variant="outline" disabled>
          Next question
          <ChevronRight aria-hidden="true" />
        </Button>
      )}
    </div>
  )
}

function GradeFeedback({ verdict, feedback }: { verdict: QuizGradeResult['verdict']; feedback: string }) {
  const labelStyle =
    verdict === 'correct'
      ? 'text-emerald-600 dark:text-emerald-400'
      : verdict === 'partial'
        ? 'text-foreground/80'
        : 'text-destructive'
  const label = verdict === 'correct' ? 'Correct' : verdict === 'partial' ? 'Almost there' : 'Not quite'
  return (
    <div role="status" aria-live="polite" className="mt-3 border-t border-border/50 pt-2.5">
      <p className={cn('text-xs font-semibold', labelStyle)}>{label}</p>
      <QuizMarkdown text={feedback} className="mt-0.5 text-foreground/80" />
    </div>
  )
}

function SelfCheckPanel({
  question,
  onGotIt,
  onKeepTrying,
}: {
  question: TextQuestion
  onGotIt: () => void
  onKeepTrying: () => void
}) {
  return (
    <div className="mt-3 border-t border-border/50 pt-2.5 space-y-2">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
        Compare against
      </p>
      <QuizMarkdown text={question.explanation ?? question.rubric} className="text-foreground/85" />
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={onGotIt}>
          I got it
        </Button>
        <Button size="sm" variant="ghost" onClick={onKeepTrying}>
          Keep trying
        </Button>
      </div>
    </div>
  )
}

function QuizHints({ hints }: { hints: string[] }) {
  const [shown, setShown] = React.useState(0)
  if (hints.length === 0) return null
  return (
    <>
      {shown > 0 && (
        <div className="mt-2.5 space-y-2">
          {hints.slice(0, shown).map((hint, index) => (
            <div key={index} className="flex items-start gap-2 text-muted-foreground">
              <Lightbulb className="size-3.5 shrink-0 mt-0.5 text-muted-foreground/60" aria-hidden="true" />
              <QuizMarkdown text={hint} className="text-muted-foreground" />
            </div>
          ))}
        </div>
      )}
      {shown < hints.length && (
        <button
          type="button"
          onClick={() => setShown((n) => n + 1)}
          className="mt-2 block text-xs text-muted-foreground/70 hover:text-foreground transition-colors cursor-pointer"
        >
          Show hint{hints.length > 1 ? ` (${shown + 1}/${hints.length})` : ''}
        </button>
      )}
    </>
  )
}

function QuizExplanation({ text }: { text: string }) {
  return (
    <div className="mt-3 border-t border-border/50 pt-2.5">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
        Explanation
      </p>
      <QuizMarkdown text={text} className="text-foreground/85" />
    </div>
  )
}

function QuizMarkdown({ text, className }: { text: string; className?: string }) {
  return (
    <div
      className={cn(
        'text-sm leading-relaxed [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={QUIZ_REMARK} rehypePlugins={QUIZ_REHYPE}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

function storedQuizKeys(documents: DocumentListItem[] | undefined, documentId: string): string[] {
  const doc = documents?.find((d) => d.id === documentId)
  const quiz = ((doc?.metadata ?? {}) as Record<string, unknown>).quiz
  if (!Array.isArray(quiz)) return []
  return quiz.filter((key): key is string => typeof key === 'string')
}
