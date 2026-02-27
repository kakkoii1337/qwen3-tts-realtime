# test_voice_design.ps1 -- Shakespeare TTS demo: Othello, Act III Scene III
#                          VoiceDesign model -- instruct only, no named speakers
#
# Test 1 -- Narrator:  neutral, clear delivery
# Test 2 -- Othello:   jealousy & rage
# Test 3 -- Desdemona: love & joy
#
# Usage: .\test_voice_design.ps1

$Speak = Join-Path $PSScriptRoot "speak.ps1"

# ---------------------------------------------------------------------------
# Test 1 -- Narrator (neutral instruct)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 1 / 3  |  Narrator -- Scene Setting ===" -ForegroundColor Cyan

& $Speak @"
In the sun-drenched gardens of the citadel at Cyprus, Othello the Moor -- celebrated general, devoted husband -- walks in quiet conversation with his ensign Iago. His young wife Desdemona has just departed, her words sweet and full of confidence, having pleaded the case of the disgraced lieutenant Cassio. Yet Iago remains, and in the space between one breath and the next, he has begun his work. With artful pauses, half-spoken doubts, and feigned reluctance, he has pressed a single poisoned thought into the general's mind: that Desdemona's love may not be what it seems. Othello, a man who has faced cannon and tempest without flinching, now stands at the edge of an abyss he cannot name. And Desdemona -- innocent, radiant, utterly unaware -- tends her flowers on the other side of the garden, singing softly to herself.
"@ -Instruct "A distinguished, authoritative narrator voice with a warm, measured baritone -- speak with the gravitas of a BBC documentary narrator. Keep a steady, unhurried pace at approximately 140 words per minute with deliberate pauses at sentence boundaries (2 beats after each period). Use gentle downward inflection on declarative statements to convey authority without monotony. Maintain a slight forward resonance in the chest voice to create intimacy. When mentioning character names -- 'Othello,' 'Desdemona,' 'Iago,' 'Cassio' -- give each name slight emphasis and warmth as if introducing important figures. For the phrase 'poisoned thought' and 'abyss he cannot name,' drop your pitch marginally lower and slow your pace by 10% to create atmosphere and gravity. Never rush; let the imagery of 'sun-drenched gardens' and 'tends her flowers' breathe with subtle lyrical quality. Overall tone: wise, trustworthy, omniscient storyteller."

# ---------------------------------------------------------------------------
# Test 2 -- Othello (extreme negative)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 2 / 3  |  Othello -- Jealousy & Rage ===" -ForegroundColor Red

& $Speak @"
O, now, forever farewell the tranquil mind! Farewell content! Farewell the plumed troop, and the big wars that make ambition virtue! O, farewell! Farewell the neighing steed, and the shrill trump, the spirit-stirring drum, the ear-piercing fife -- the royal banner, and all quality, pride, pomp, and circumstance of glorious war! And O you mortal engines, whose rude throats the immortal Jove's dread clamours counterfeit -- farewell! Othello's occupation's gone! I had rather be a toad and live upon the vapour of a dungeon than keep a corner in the thing I love for others' uses. O curse of marriage, that we can call these delicate creatures ours and not their appetites!
"@ -Instruct "A deep, powerfully resonant bass-baritone voice carrying the weight of a battle-hardened general -- speak as if your throat is choked with sand and your heart is imploding. This is the most intense emotional arc in all of theatre: begin with RESIGNATION and measured devastation ('O, now, forever farewell the tranquil mind') -- your voice should crack slightly on 'forever,' with a long 3-beat pause after. Then build the list of farewells with GROWING INTENSITY: each 'farewell' grows louder and more ragged, reaching toward a scream by the third. The phrase 'O curse of marriage' is the CLIMAX -- drop to a near-whisper of bitter contempt, then EXPLODE with 'delicate creatures ours and not their appetites' spit with venom. Use VOCAL TREMOR throughout when mentioning Desdemona -- let your voice shake with barely contained fury. Pause 2 beats after 'O, farewell!' (the single one) for effect. Throughout: GUTTURAL quality, as if each word is being torn from your chest. The final 'appetites' should drip with disgust. If you could weep blood, you would. You are a man watching his world burn."

# ---------------------------------------------------------------------------
# Test 3 -- Desdemona (extreme positive)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 3 / 3  |  Desdemona -- Love & Devotion ===" -ForegroundColor Green

& $Speak @"
That I did love the Moor to live with him, my downright violence and storm of fortunes may trumpet to the world! My heart's subdued even to the very quality of my lord. I saw Othello's visage in his mind, and to his honours and his valiant parts did I my soul and fortunes consecrate. So that, dear friends, if I be left behind, a moth of peace while he goes to the war, the rites for which I love him are bereft me -- let me go with him! I am not frivolous of spirit, nor light of love. I have known no other heart but his. He is the sun to me, and I the flower that turns to meet him -- and I would not trade this love for all the kingdoms of the earth!
"@ -Instruct "A luminous, ethereal soprano voice young and pure as morning -- speak with the desperate sincerity of a woman pleading for her life's greatest truth. Your voice should shimmer with barely contained emotion, like sunlight on water. Begin with FERVENT DECLARATION: 'That I did love the Moor' -- emphasize 'love' as if your life depends on it, because it does. The phrase 'my downright violence and storm of fortunes' should carry a slight defiant edge -- you DEFY anyone to question your devotion. When you say 'I saw Othello's visage in his mind,' let your voice go SOFT with reverie, as if seeing his face in a dream. The clause 'to his honours and his valiant parts did I my soul and fortunes consecrate' should build with SACRED intensity, as if taking a holy vow. The plea 'let me go with him!' is the EMOTIONAL HEART -- break slightly on 'him,' voice cracking with yearning. For 'He is the sun to me, and I the flower that turns to meet him' -- speak with WONDER, like a poet discovering the perfect metaphor for the first time, your pitch rising gently on 'sun' and 'flower.' The final declaration 'I would not trade this love for all the kingdoms of the earth!' should ring with absolute conviction and defiant certainty. Throughout: use BREATHY quality on words like 'heart,' 'soul,' 'love,' 'devotion' to convey vulnerable openness. You are innocence on trial, and love is your only defense."

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== All 3 tests complete ===" -ForegroundColor Cyan
Write-Host ""
