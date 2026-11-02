// Copyright (c) 2026 DeepBeepMeep - part of WanGP, WanGP Community License 2.0 (see LICENSE.txt)
// hoodtronik fork: Scenes. A movie (its cast, sets and style shared) and its scenes, each scene switching on only the cast and sets it uses
// (see movies.py). On a movie: its scenes in order, Add scene from a recipe, the movie cut. On a scene: what it uses, back to its movie.
// On any other production: make it a movie, or file it under one.
import { state, actions } from './app.js';
import { api } from './api.js';
import { icon, esc, h, art, formatDuration, menu, confirmDialog, promptDialog, toast } from './ui.js';
import { KINDS, kindTiles } from './home.js';

const STAGE_LABELS = { brief: 'Brief', planning: 'Planning', review: 'In review', shooting: 'Shooting', editing: 'Editing', delivered: 'Delivered' };

export function mountScenes(container) {
  let token = 0;
  async function render() {
    const doc = state.doc, mine = ++token;
    try {
      if (doc.is_movie) await renderMovie(container, doc, () => mine !== token);
      else if (doc.movie) await renderScene(container, doc, () => mine !== token);
      else await renderPlain(container, doc, () => mine !== token);
    } catch (error) { if (mine === token) container.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`; }
  }
  render();
  return { update: render };
}

// A movie -------------------------------------------------------------------------------------------------------------------------------
async function renderMovie(container, doc, stale) {
  const [{ scenes }, { recipes }] = await Promise.all([api.scenes(doc.id), api.recipes()]);
  if (stale()) return;
  const live = scenes.filter(scene => !scene.archived), archived = scenes.filter(scene => scene.archived);
  const cuts = doc.deliverables.filter(item => item.method === 'movie');
  const cut = cuts[cuts.length - 1];
  const total = live.reduce((sum, scene) => sum + (scene.duration_s || 0), 0);
  container.innerHTML = `<div class="scenes-page">
    <div class="toolbar"><h2>Scenes</h2><span class="stat">${live.length} ${live.length === 1 ? 'scene' : 'scenes'} · ${formatDuration(total)} · cast, sets and style are shared from this movie</span><div class="grow"></div>
      <button class="btn small" id="movie-cut" title="Join each scene's latest version, in this order, into one film">${icon('film')} Make the movie cut</button>
      <button class="btn primary small" id="scene-add">${icon('plus')} Add scene</button></div>
    ${cut ? `<div class="movie-cut"><video controls preload="metadata" src="${actions.file(cut.path)}"></video><div class="col"><b>Movie cut</b><span class="muted">${cut.scenes} scenes · ${formatDuration(cut.duration_s)}${cut.missing?.length ? ` · left out (no version yet): ${esc(cut.missing.join(', '))}` : ''}</span>
      <a class="btn small" href="${api.file(doc.id, cut.path, true)}" download>${icon('download')} Download</a></div></div>` : ''}
    <div class="scene-list">${live.length ? live.map((scene, index) => sceneRow(doc, scene, index, live.length)).join('') : `<div class="empty-state">No scene yet. Add one: pick a recipe and switch on the characters and sets it needs.</div>`}</div>
    ${archived.length ? `<details class="archived-productions"><summary class="section-title">${icon('chevron', 'chev')} Archived scenes <span class="muted">${archived.length}</span></summary>
      <div class="scene-list">${archived.map((scene, index) => sceneRow(doc, scene, index, archived.length, true)).join('')}</div></details>` : ''}
    <div class="section-title" style="margin-top:28px">${icon('note')} Scene recipes <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">the starting setup you pick when you add a scene</span></div>
    <div class="recipe-list">${recipes.map(recipe => `<div class="recipe"><b>${esc(recipe.name)}</b>${recipe.built_in ? '<span class="chip">built in</span>' : `<button class="btn small ghost icon" data-drop-recipe="${esc(recipe.name)}" title="Delete this recipe">${icon('trash')}</button>`}
      <span class="muted">${esc(recipe.description || recipe.notes || '')}</span></div>`).join('')}</div>
  </div>`;
  const order = live.map(scene => scene.id);
  container.querySelector('#scene-add').onclick = () => addScene(doc, recipes);
  container.querySelector('#movie-cut').onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true;
    toast('Joining the scenes…');
    try { await api.assembleMovie(doc.id); toast('The movie cut is ready.', 'ok'); } catch (error) { toast(error.message, 'error'); } finally { button.disabled = false; }
  };
  container.querySelectorAll('[data-drop-recipe]').forEach(button => button.onclick = async () => {
    if (await confirmDialog({ title: `Delete the recipe "${button.dataset.dropRecipe}"?`, text: 'Scenes made from it keep their setup.', ok: 'Delete', danger: true })) {
      await api.deleteRecipe(button.dataset.dropRecipe);
      renderMovie(container, state.doc, stale);
    }
  });
  container.querySelectorAll('.scene-row').forEach(row => {
    const id = row.dataset.scene, scene = scenes.find(item => item.id === id);
    row.onclick = event => { if (!event.target.closest('button')) location.hash = `#/p/${id}/storyboard`; };
    row.querySelector('[data-up]')?.addEventListener('click', () => move(id, -1));
    row.querySelector('[data-down]')?.addEventListener('click', () => move(id, 1));
    row.querySelector('[data-uses]').onclick = () => editUses(doc, scene);
    row.querySelector('.menu-btn').onclick = event => menu(event.currentTarget, [
      { label: 'Open', icon: 'expand', action: () => location.hash = `#/p/${id}/storyboard` },
      { label: 'Characters and sets…', icon: 'users', action: () => editUses(doc, scene) },
      { label: 'Rename…', icon: 'note', action: async () => {
        const title = await promptDialog({ title: 'Rename the scene', value: scene.title, ok: 'Rename' });
        if (title?.trim()) { await api.ops(id, [{ op: 'brief', fields: { title: title.trim() } }]); renderMovie(container, state.doc, stale); }
      } },
      { label: 'Save its setup as a recipe…', icon: 'copy', action: () => saveRecipe(id, scene.title) },
      { label: 'Duplicate', icon: 'copy', action: async () => { await api.duplicate(id); toast('Duplicated: the copy is the last scene.', 'ok'); renderMovie(container, state.doc, stale); } },
      { label: scene.archived ? 'Bring back' : 'Archive', icon: scene.archived ? 'undo' : 'archive', action: async () => { await api.archive(id, !scene.archived); renderMovie(container, state.doc, stale); } },
      { label: 'Take it out of the movie', icon: 'x', action: async () => {
        if (await confirmDialog({ title: 'Take this scene out of the movie?', text: 'It becomes a production of its own on the home page, keeping a copy of the cast and sets it uses.', ok: 'Take out' })) {
          await api.fileUnder(id, null); renderMovie(container, state.doc, stale);
        }
      } },
    ]);
  });
  async function move(id, step) {
    const index = order.indexOf(id), next = index + step;
    if (next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    await api.sceneOrder(doc.id, order);
    renderMovie(container, state.doc, stale);
  }
}

function sceneRow(movie, scene, index, count, archived = false) {
  const castNames = (scene.uses?.cast || []).map(id => movie.cast.find(member => member.id === id)?.name).filter(Boolean);
  const sets = scene.uses?.locations || [];
  const cover = scene.poster ? `<img loading="lazy" src="${api.file(scene.id, scene.poster)}" alt="">` : `<div class="placeholder" style="${art(scene.id, 'film')}">${icon('clapper')}</div>`;
  const progress = scene.shots ? Math.round(100 * scene.approved / scene.shots) : 0;
  return `<article class="scene-row" data-scene="${esc(scene.id)}">
    <div class="scene-num">${archived ? '' : index + 1}</div>
    <div class="scene-cover">${cover}</div>
    <div class="scene-body"><div class="row"><b>${esc(scene.title)}</b>${KINDS[scene.kind] ? `<span class="chip">${esc(KINDS[scene.kind].label)}</span>` : ''}${scene.recipe ? `<span class="chip">${esc(scene.recipe)}</span>` : ''}<span class="chip">${esc(STAGE_LABELS[scene.stage] || scene.stage)}</span></div>
      ${scene.concept ? `<div class="muted scene-concept">${esc(scene.concept.split('\n')[0])}</div>` : ''}
      <div class="row scene-uses">${scene.uses ? `${icon('users')}<span>${castNames.length ? esc(castNames.join(', ')) : 'no cast'}</span><span>·</span>${icon('image')}<span>${sets.length ? esc(sets.join(', ')) : 'no set'}</span>` : `<span class="muted">Filed here (its own cast and sets, not synced)</span>`}</div>
      <div class="progress" title="${scene.approved}/${scene.shots} shots approved"><i style="width:${progress}%"></i></div>
      <div class="muted scene-meta">${scene.shots} shots · ${scene.approved} approved · ${formatDuration(scene.duration_s)}${scene.latest ? ' · has a version' : ' · no version yet'}</div></div>
    <div class="scene-actions">${archived ? '' : `<button class="btn small ghost icon" data-up title="Earlier" ${index ? '' : 'disabled'}>${icon('chevron', 'up')}</button><button class="btn small ghost icon" data-down title="Later" ${index < count - 1 ? '' : 'disabled'}>${icon('chevron', 'down')}</button>`}
      <button class="btn small" data-uses ${scene.uses ? '' : 'disabled'} title="Which characters and sets this scene uses">${icon('users')} Uses</button><button class="btn small ghost icon menu-btn" title="More">${icon('more')}</button></div>
  </article>`;
}

// The asset picker: the movie's cast and sets as toggles ---------------------------------------------------------------------------------
function pickerHtml(movie, uses) {
  const cast = movie.cast.map(member => {
    const picture = member.master || member.images[0];
    return `<label class="pick ${uses.cast.includes(member.id) ? 'on' : ''}"><input type="checkbox" data-cast="${esc(member.id)}" ${uses.cast.includes(member.id) ? 'checked' : ''}>
      ${picture ? `<img src="${api.file(movie.id, picture)}" alt="">` : `<span class="ph" style="${art(member.id, member.name)}"></span>`}<span>${esc(member.name || member.id)}</span></label>`;
  }).join('');
  const sets = (movie.brief.locations || []).filter(place => place.name).map(place => {
    const picture = place.references?.[0];
    return `<label class="pick ${uses.locations.includes(place.name) ? 'on' : ''}"><input type="checkbox" data-set="${esc(place.name)}" ${uses.locations.includes(place.name) ? 'checked' : ''}>
      ${picture ? `<img src="${api.file(movie.id, picture)}" alt="">` : `<span class="ph" style="${art(place.name, 'set')}"></span>`}<span>${esc(place.name)}</span></label>`;
  }).join('');
  return `<div class="picker"><div class="section-title">${icon('users')} Characters</div><div class="picks">${cast || '<span class="muted">The movie has no cast yet (its Cast page).</span>'}</div>
    <div class="section-title">${icon('image')} Sets</div><div class="picks">${sets || '<span class="muted">The movie has no sets yet (its Sets page).</span>'}</div></div>`;
}

function readPicker(root) {
  root.querySelectorAll('.pick').forEach(label => label.classList.toggle('on', label.querySelector('input').checked));
  return { cast: [...root.querySelectorAll('[data-cast]:checked')].map(input => input.dataset.cast), locations: [...root.querySelectorAll('[data-set]:checked')].map(input => input.dataset.set) };
}

function modal(html) {
  const back = h(`<div class="modal-back"><div class="modal wide" role="dialog" aria-modal="true">${html}</div></div>`);
  document.getElementById('overlay-root').append(back);
  back.addEventListener('change', () => readPicker(back));
  return back;
}

function addScene(movie, recipes) {
  const back = modal(`<h3>Add a scene to ${esc(movie.title)}</h3>
    <input class="input" id="sc-title" placeholder="Scene name (Queen's audience, The door…)">
    <textarea class="textarea" id="sc-concept" rows="3" placeholder="What happens in this scene (the showrunner also reads the movie's story and the scenes around it)"></textarea>
    <label class="muted" style="font-size:12.5px">Format</label>
    <div class="kind-row">${kindTiles(KINDS[movie.brief.kind] ? movie.brief.kind : 'short_film')}</div>
    <label class="muted" style="font-size:12.5px">Recipe (optional: a starting setup on top of the format)</label>
    <select class="input" id="sc-recipe"><option value="">None: the movie's settings</option>${recipes.map(recipe => `<option value="${esc(recipe.name)}">${esc(recipe.name)}${recipe.description ? ` · ${esc(recipe.description)}` : ''}</option>`).join('')}</select>
    ${pickerHtml(movie, { cast: [], locations: [] })}
    <div class="actions"><button class="btn ghost" data-r="0">Cancel</button><button class="btn primary" data-r="1">Add scene</button></div>`);
  back.querySelector('#sc-title').focus();
  back.addEventListener('click', async event => {
    const tile = event.target.closest('[data-kind]');
    if (tile) back.querySelectorAll('[data-kind]').forEach(button => button.classList.toggle('on', button === tile));
    if (event.target === back || event.target.closest('[data-r="0"]')) back.remove();
    if (!event.target.closest('[data-r="1"]')) return;
    const title = back.querySelector('#sc-title').value.trim() || 'New scene';
    event.target.closest('button').disabled = true;
    try {
      const scene = await api.createScene(movie.id, { title, kind: back.querySelector('[data-kind].on')?.dataset.kind || null, recipe: back.querySelector('#sc-recipe').value || null, concept: back.querySelector('#sc-concept').value, uses: readPicker(back) });
      back.remove();
      location.hash = `#/p/${scene.id}/brief`;
    } catch (error) { toast(error.message, 'error'); event.target.closest('button').disabled = false; }
  });
}

async function editUses(movie, scene) {
  const back = modal(`<h3>What ${esc(scene.title)} uses</h3><p class="muted">Only these reach the showrunner for this scene. Switching one off keeps it in the movie.</p>
    ${pickerHtml(movie, scene.uses || { cast: [], locations: [] })}
    <div class="actions"><button class="btn ghost" data-r="0">Cancel</button><button class="btn primary" data-r="1">Save</button></div>`);
  back.addEventListener('click', async event => {
    if (event.target === back || event.target.closest('[data-r="0"]')) back.remove();
    if (!event.target.closest('[data-r="1"]')) return;
    try { await api.uses(scene.id, readPicker(back)); back.remove(); toast('Saved.', 'ok'); if (state.doc) actions.refresh?.(); mounted(); } catch (error) { toast(error.message, 'error'); }
  });
  function mounted() { const view = document.getElementById('view'); if (view && state.doc?.is_movie) renderMovie(view, state.doc, () => false); }
}

async function saveRecipe(sceneId, title) {
  const name = await promptDialog({ title: 'Save this scene\'s setup as a recipe', text: 'Its kind, pacing, review and format settings and its model picks. New scenes can start from it.', value: title, ok: 'Save' });
  if (!name?.trim()) return;
  const notes = await promptDialog({ title: 'Notes for the showrunner (optional)', text: 'Read as the start of every scene made from this recipe.', multiline: true, ok: 'Save' });
  try { await api.saveRecipe({ name: name.trim(), notes: notes || '', from_scene: sceneId }); toast(`Recipe "${name.trim()}" saved.`, 'ok'); } catch (error) { toast(error.message, 'error'); }
}

// A scene -------------------------------------------------------------------------------------------------------------------------------
async function renderScene(container, doc, stale) {
  const movie = await api.get(doc.movie);
  if (stale()) return;
  const context = doc.movie_context || {};
  container.innerHTML = `<div class="scenes-page">
    <div class="toolbar"><button class="btn small" id="to-movie">${icon('chevron', 'back')} ${esc(movie.title)}</button><h2>${context.position ? `Scene ${context.position} of ${context.of}` : 'Scene'}</h2><div class="grow"></div>
      <button class="btn small" id="save-recipe">${icon('copy')} Save setup as a recipe</button></div>
    ${doc.uses ? `<p class="muted">The characters and sets switched on here are the only ones the showrunner sees for this scene. Their cards are the movie's: an edit here reaches every scene. Characters you add on this scene's Cast page stay its own.</p>
      <div id="uses-picker">${pickerHtml(movie, doc.uses)}</div><div class="row"><div class="grow"></div><button class="btn primary small" id="uses-save">Save</button></div>`
      : `<div class="empty-state">This production is filed under the movie but keeps its own cast and sets (it was made before it joined the movie).</div>`}
    <div class="section-title" style="margin-top:22px">${icon('layers')} Around it</div>
    <div class="muted">${context.previous ? `Before: <b>${esc(context.previous.title)}</b>` : 'The first scene.'} · ${context.next ? `After: <b>${esc(context.next.title)}</b>` : 'The last scene.'}</div>
  </div>`;
  container.querySelector('#to-movie').onclick = () => location.hash = `#/p/${movie.id}/scenes`;
  container.querySelector('#save-recipe').onclick = () => saveRecipe(doc.id, doc.recipe || doc.title);
  const picker = container.querySelector('#uses-picker');
  if (picker) {
    picker.addEventListener('change', () => readPicker(picker));
    container.querySelector('#uses-save').onclick = async () => {
      try { await api.uses(doc.id, readPicker(picker)); toast('Saved: the scene now uses these.', 'ok'); } catch (error) { toast(error.message, 'error'); }
    };
  }
}

// Any other production ------------------------------------------------------------------------------------------------------------------
async function renderPlain(container, doc, stale) {
  const { productions } = await api.state();
  if (stale()) return;
  const movies = productions.filter(item => item.is_movie && item.id !== doc.id);
  container.innerHTML = `<div class="scenes-page"><div class="toolbar"><h2>Scenes</h2></div>
    <div class="scene-choice"><div class="col"><b>Make this production a movie</b><span class="muted">Its cast, sets and style become the shared library; you add scenes here, each using only the characters and sets it needs. The home page shows the movie as one card.</span>
      <button class="btn primary small" id="make-movie">${icon('film')} Make it a movie</button></div>
    ${movies.length ? `<div class="col"><b>Or file it under a movie</b><span class="muted">It becomes one of that movie's scenes, keeping its own cast and sets.</span>
      <div class="row"><select class="input" id="movie-pick">${movies.map(item => `<option value="${esc(item.id)}">${esc(item.title)}</option>`).join('')}</select><button class="btn small" id="file-under">File it</button></div></div>` : ''}</div></div>`;
  container.querySelector('#make-movie').onclick = async () => {
    try { await api.makeMovie(doc.id, true); toast('It is a movie now: add its scenes here.', 'ok'); } catch (error) { toast(error.message, 'error'); }
  };
  container.querySelector('#file-under')?.addEventListener('click', async () => {
    try { await api.fileUnder(doc.id, container.querySelector('#movie-pick').value); toast('Filed under the movie.', 'ok'); } catch (error) { toast(error.message, 'error'); }
  });
}
