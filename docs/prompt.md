# Posto de Gasolina Retrô no Deserto — prompt otimizado (EN) para geradores de imagem

## Prompt
```
Isometric orthographic 3D diorama of a 1960s-70s retro desert gas station on a floating square chunk of earth, night scene.
Detailed low poly, flat shading, visible facets, game-asset style, Blender Cycles render, clean studio-quality, 1:1.

Subject: small mid-century service station with a wedge-shaped angular flat roof on rusty angular metal pillars;
faded beige walls with worn orange and red horizontal stripes; large glass windows glowing dim warm amber from inside.
Two vintage angular gas pumps (one red, one blue) with small glowing globes on top, low-poly hoses, on a raised concrete island under the canopy.
Tall crooked rusty "GAS" sign in the foreground, red and blue neon tubes with a few flickering/dead segments, retro arrow on top.
Cracked asphalt with jagged fissures, sand creeping over the edges. Angular saguaro cacti, dry bushes, angular rocks, scattered retro debris (barrels, tires, crates).

Lighting: dark navy night sky, faint blue moonlight rim; warm amber light pools under the canopy and from the windows,
a single street lamp casting an amber cone onto the cracked ground, soft volumetric light shafts, red/blue neon glow on nearby surfaces.
High contrast, rich shadows, cinematic, sharp focus.
```

## Negative prompt
```
smooth shading, photorealistic, realistic textures, perspective distortion, fisheye, daylight, blurry, text artifacts,
extra letters, people, cars, watermark, logo, cropped, cluttered background
```

## Por que ficou melhor
- Inglês e frases curtas: geradores respondem melhor a termos de estilo conhecidos (*isometric, low poly, flat shading, Blender Cycles*).
- Ordem por prioridade: estilo/ângulo → assunto → iluminação. O original misturava tudo em seções longas.
- Proporção `1:1` explícita (o bloco flutuante é quadrado); acrescentei prompt negativo.

## Sugestões de melhoria (e o que foi aplicado no render em Blender)
1. **Telhado × câmera isométrica**: um telhado grande esconde bombas e loja. Aplicado: cobertura só sobre as bombas, telhado próprio na loja.
2. **Composição**: placa GAS no canto frontal esquerdo e poste de luz no direito, para não taparem as bombas.
3. **Volumetria barata**: cones de luz falsos (malha transparente + emissão) em vez de volume real, que fica lento e ruidoso.
4. **Neon com falhas**: segmentos "apagados" nas letras e na seta (G, A e S têm tubos mortos).
5. **Próximas ideias**: céu estrelado, tumbleweed, carro velho abandonado, fumaça/vapor da loja, poças com reflexo do neon no asfalto, e sombras de contato mais fortes sob o bloco.

## Arquivos
- `generate_posto_retro_lowpoly.py` — gera tudo (procedural). Uso:
  `blender -b --python generate_posto_retro_lowpoly.py -- C:/caminho/saida.png [amostras] [resolução] [CYCLES|EEVEE]`
- `docs/render.png` — render final (1600 px, Cycles, 192 amostras)
- `posto_retro_render.blend` — cena para ajustar no Blender
