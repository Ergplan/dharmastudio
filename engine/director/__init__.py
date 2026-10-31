"""The Art Director: an agent that turns a scene brief into a finished comic page while enforcing the author's
master art-direction prompt (engine/director/master_prompt.md, used verbatim) as guardrails.

guardrails.py  parse the master prompt into structured rules (the raw text is kept and is the authority)
chapters.py    studio chapter -> manuscript chapter (Book, number, title, text, scene settings, cast, age)
brief.py       the scene brief and its deterministic validators (verbatim lines, character keys, lock gate)
agent.py       plan -> prompt -> paint -> critic -> revise -> assemble (pure logic; the studio glue is backend/director.py)
painted.py     painted-page mode: the house style, the whole-page prompt with exact box texts, the text check
cover.py       volume covers and posters: the poster art prompt and the typeset title block (exact spelling)
"""
