# llm-vendor-scorecard
Comparing 4 AI models on 20 consulting tasks for quality, risk and cost.
Work in progress - Day 1
models:
  - id: nvidia/nemotron-3-ultra-550b-a55b:free
    label: Large (NVIDIA)
  - id: thinkingmachines/inkling:free
    label: Mid reasoning (Thinking Machines)
  - id: google/gemma-4-31b-it:free
    label: Mid open (Google)
  - id: liquid/lfm-2.5-2.6b:free
    label: Small (Liquid AI)

judge: nvidia/nemotron-3.5-super-vl:free