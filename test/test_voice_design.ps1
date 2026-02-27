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
"@ -Instruct "A clear, measured narrator voice -- calm, authoritative, and unhurried, drawing the listener into the scene"

# ---------------------------------------------------------------------------
# Test 2 -- Othello (extreme negative)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 2 / 3  |  Othello -- Jealousy & Rage ===" -ForegroundColor Red

& $Speak @"
O, now, forever farewell the tranquil mind! Farewell content! Farewell the plumed troop, and the big wars that make ambition virtue! O, farewell! Farewell the neighing steed, and the shrill trump, the spirit-stirring drum, the ear-piercing fife -- the royal banner, and all quality, pride, pomp, and circumstance of glorious war! And O you mortal engines, whose rude throats the immortal Jove's dread clamours counterfeit -- farewell! Othello's occupation's gone! I had rather be a toad and live upon the vapour of a dungeon than keep a corner in the thing I love for others' uses. O curse of marriage, that we can call these delicate creatures ours and not their appetites!
"@ -Instruct "A deep, resonant male voice breaking apart with overwhelming grief and volcanic rage -- trembling with jealousy, barely containing explosive fury, each word torn from a soul in agony"

# ---------------------------------------------------------------------------
# Test 3 -- Desdemona (extreme positive)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== TEST 2 / 3  |  Desdemona -- Love & Joy ===" -ForegroundColor Green

& $Speak @"
That I did love the Moor to live with him, my downright violence and storm of fortunes may trumpet to the world! My heart's subdued even to the very quality of my lord. I saw Othello's visage in his mind, and to his honours and his valiant parts did I my soul and fortunes consecrate. So that, dear friends, if I be left behind, a moth of peace while he goes to the war, the rites for which I love him are bereft me -- let me go with him! I am not frivolous of spirit, nor light of love. I have known no other heart but his. He is the sun to me, and I the flower that turns to meet him -- and I would not trade this love for all the kingdoms of the earth!
"@ -Instruct "A warm, luminous young female voice overflowing with radiant joy, breathless adoration, and pure happiness -- glowing with total devotion, every word lit from within by love"

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== All 3 tests complete ===" -ForegroundColor Cyan
Write-Host ""
