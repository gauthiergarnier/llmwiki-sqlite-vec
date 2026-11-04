import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from '@/lib/api'
import { parseQuizYaml } from '@/lib/quiz/parseQuiz'
import { questionKey } from '@/lib/quiz/questionKey'
import { QuizBlock } from './QuizBlock'

vi.mock('@/stores', () => ({
  useUserStore: (selector: (state: { accessToken: string }) => unknown) =>
    selector({ accessToken: 'test-token' }),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>()
  return { ...original, apiFetch: vi.fn() }
})

const apiFetchMock = vi.mocked(apiFetch)
const source = `questions:
  - type: text
    prompt: Why does the base rate matter?
    rubric: Correct if the answer connects rarity to false positives.
    explanation: A low prior can make false positives outnumber true positives.
`

const multiQuestionSource = `title: "Checkpoint: Bayes review"
questions:
  - prompt: Which quantity is the prior probability?
    options:
      - P(disease)
      - P(positive | disease)
      - P(disease | positive)
    answer: 0
    explanation: The prior is the probability assigned before seeing the test result.
  - prompt: What does a likelihood describe?
    options:
      - Evidence under a hypothesis
      - The final posterior only
      - The sample size
    answer: 0
    explanation: A likelihood asks how compatible the evidence is with a hypothesis.
  - prompt: Which rule combines a prior and likelihood?
    options:
      - Bayes' rule
      - The central limit theorem
      - Jensen's inequality
    answer: 0
    explanation: Bayes' rule updates the prior with the likelihood.
`

const freeFormFlowSource = `questions:
  - type: text
    prompt: Explain why the prior matters.
    rubric: Correct if the answer connects the prior to posterior probability.
    explanation: The posterior combines the prior with the likelihood.
  - prompt: Which term describes P(hypothesis) before seeing evidence?
    options: [Prior, Likelihood, Posterior]
    answer: 0
    explanation: The prior is assigned before observing the evidence.
`

afterEach(cleanup)

describe('QuizBlock question flow', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('renders one question at a time with Quiz terminology', () => {
    render(
      <QuizBlock
        source={multiQuestionSource}
        documentId="quiz-flow-one-at-a-time"
        documentsRef={{ current: [] } as never}
      />,
    )

    expect(screen.getByText('Quiz')).toBeTruthy()
    expect(screen.queryByText(/Checkpoint/)).toBeNull()
    expect(screen.getByText('Question 1 of 3')).toBeTruthy()
    expect(screen.getByText('Which quantity is the prior probability?')).toBeTruthy()
    expect(screen.queryByText('What does a likelihood describe?')).toBeNull()
    expect(screen.queryByText('Which rule combines a prior and likelihood?')).toBeNull()
  })

  it('keeps the explanation visible and gates the next question on a correct answer', () => {
    render(
      <QuizBlock
        source={multiQuestionSource}
        documentId="quiz-flow-navigation"
        documentsRef={{ current: [] } as never}
      />,
    )

    const next = screen.getByRole('button', { name: 'Next question' }) as HTMLButtonElement
    expect(next.disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'P(disease | positive)' }))
    expect(next.disabled).toBe(true)
    expect(screen.getByText('Which quantity is the prior probability?')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'P(disease)' }))
    expect(screen.getByText('The prior is the probability assigned before seeing the test result.')).toBeTruthy()
    expect(next.disabled).toBe(false)

    fireEvent.click(next)
    expect(screen.getByText('Question 2 of 3')).toBeTruthy()
    expect(screen.getByText('What does a likelihood describe?')).toBeTruthy()
    expect(screen.queryByText('Which quantity is the prior probability?')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(screen.getByText('Question 1 of 3')).toBeTruthy()
    expect(screen.getByText('The prior is the probability assigned before seeing the test result.')).toBeTruthy()
  })

  it('resumes at the first incomplete persisted question', () => {
    const parsed = parseQuizYaml(multiQuestionSource)
    if (!parsed.spec) throw new Error(parsed.error)
    const firstKey = questionKey(multiQuestionSource, parsed.spec.questions[0], 0)

    render(
      <QuizBlock
        source={multiQuestionSource}
        documentId="quiz-flow-resume"
        documentsRef={{ current: [{ id: 'quiz-flow-resume', metadata: { quiz: [firstKey] } }] } as never}
      />,
    )

    expect(screen.getByText('Question 2 of 3')).toBeTruthy()
    expect(screen.getByText('What does a likelihood describe?')).toBeTruthy()
    expect(screen.queryByText('Which quantity is the prior probability?')).toBeNull()
  })
})

describe('QuizBlock free-form questions', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('renders a quiet completed state instead of an empty disabled answer', () => {
    const parsed = parseQuizYaml(source)
    if (!parsed.spec) throw new Error(parsed.error)
    const key = questionKey(source, parsed.spec.questions[0], 0)
    const documentsRef = {
      current: [{ id: 'doc-1', metadata: { quiz: [key] } }],
    }

    render(
      <QuizBlock
        source={source}
        documentId="doc-1"
        documentsRef={documentsRef as never}
      />,
    )

    expect(screen.queryByRole('textbox', { name: 'Your answer' })).toBeNull()
    expect(screen.getByText('Completed')).toBeTruthy()
    expect(screen.getByText('Explanation')).toBeTruthy()
  })

  it('announces a daily grading limit with the server message', async () => {
    apiFetchMock.mockRejectedValueOnce(
      new ApiError(
        429,
        'Daily grading limit reached. You can check up to 100 answers in any 24-hour period.',
      ),
    )

    render(
      <QuizBlock
        source={source}
        documentId="doc-2"
        documentsRef={{ current: [] } as never}
      />,
    )

    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Because the disease is rare.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }))

    expect(
      await screen.findByText(
        'Daily grading limit reached. You can check up to 100 answers in any 24-hour period.',
      ),
    ).toBeTruthy()
    expect(screen.getByRole('status')).toBeTruthy()
  })

  it('uses one footer action to check, then advance after a correct grade', async () => {
    apiFetchMock.mockResolvedValueOnce({ verdict: 'correct', feedback: 'Good reasoning.' })

    render(
      <QuizBlock
        source={freeFormFlowSource}
        documentId="quiz-free-form-footer-flow"
        documentsRef={{ current: [] } as never}
      />,
    )

    const check = screen.getByRole('button', { name: 'Check answer' }) as HTMLButtonElement
    expect(check.closest('[data-quiz-footer]')).toBeTruthy()
    expect(check.disabled).toBe(true)
    expect(screen.queryByRole('button', { name: 'Next question' })).toBeNull()

    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'The prior is combined with the likelihood to produce the posterior.' },
    })
    expect(check.disabled).toBe(false)
    fireEvent.click(check)

    expect(await screen.findByText('Good reasoning.')).toBeTruthy()
    const next = await screen.findByRole('button', { name: 'Next question' })
    expect(screen.queryByRole('button', { name: 'Check answer' })).toBeNull()

    fireEvent.click(next)
    expect(screen.getByText('Question 2 of 2')).toBeTruthy()
    expect(screen.getByText('Which term describes P(hypothesis) before seeing evidence?')).toBeTruthy()
  })

  it('allows a partial answer to advance without being entered again', async () => {
    apiFetchMock.mockResolvedValueOnce({
      verdict: 'partial',
      feedback: 'You identified the update, but did not define the prior.',
    })

    render(
      <QuizBlock
        source={freeFormFlowSource}
        documentId="quiz-free-form-partial-advance"
        documentsRef={{ current: [] } as never}
      />,
    )

    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'The likelihood updates what we believed before.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }))

    expect(await screen.findByText('Almost there')).toBeTruthy()
    const next = await screen.findByRole('button', { name: 'Next question' })
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull()

    fireEvent.click(next)
    expect(screen.getByText('Question 2 of 2')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(screen.getByText('Completed')).toBeTruthy()
    expect(screen.queryByRole('textbox', { name: 'Your answer' })).toBeNull()
  })

  it('lets an incorrect final answer finish the quiz', async () => {
    apiFetchMock.mockResolvedValueOnce({
      verdict: 'incorrect',
      feedback: 'The answer misses the required causal link.',
    })

    render(
      <QuizBlock
        source={source}
        documentId="quiz-free-form-partial-finish"
        documentsRef={{ current: [] } as never}
      />,
    )

    const answer = screen.getByRole('textbox', { name: 'Your answer' }) as HTMLTextAreaElement
    fireEvent.change(answer, { target: { value: 'Rarity changes how a positive test should be interpreted.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check answer' }))

    expect(await screen.findByText('Not quite')).toBeTruthy()
    const finish = await screen.findByRole('button', { name: 'Finish quiz' })
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull()
    expect(answer.value).toBe('Rarity changes how a positive test should be interpreted.')
    fireEvent.click(finish)

    expect(screen.getByText('Quiz complete')).toBeTruthy()
  })
})

describe('QuizBlock invalid content', () => {
  it('shows a concise schema hint without exposing the YAML parser diagnostic', () => {
    const invalidSource = `Q: Why does the base rate matter?
- [x] Because rare events produce more false positives
`
    const parserError = parseQuizYaml(invalidSource).error
    if (!parserError) throw new Error('expected invalid quiz source')
    expect(parserError).toContain('\n')

    render(
      <QuizBlock
        source={invalidSource}
        documentId="doc-invalid"
        documentsRef={{ current: [] } as never}
      />,
    )

    const message = screen.getByRole('alert')
    expect(message.textContent).toContain('Quiz unavailable. Use YAML with a non-empty questions list.')
    expect(message.textContent).toContain('prompt')
    expect(message.textContent).toContain('zero-based answer')
    expect(message.textContent).toContain('type: text')
    expect(message.textContent).toContain('rubric')
    expect(message.textContent).not.toContain(parserError)
  })
})
