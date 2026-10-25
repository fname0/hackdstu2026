import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { TOURS, type TourModule, type TourStep } from './steps';

const PAD = 8;          // отступ подсветки от элемента
const CARD_W = 340;
const GAP = 14;         // расстояние от подсветки до карточки

interface Rect { top: number; left: number; width: number; height: number }

/** Первый видимый элемент из списка селекторов шага. */
function findTarget(step: TourStep): HTMLElement | null {
  if (!step.selector) return null;
  for (const sel of step.selector.split(',').map(s => s.trim())) {
    let els: HTMLElement[] = [];
    try { els = Array.from(document.querySelectorAll<HTMLElement>(sel)); } catch { /* :has в старом браузере */ }
    const el = els.find(e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; });
    if (el) return el;
  }
  return null;
}

/** Пошаговая подсказка по интерфейсу модуля: затемнение с «окном» вокруг блока и карточка с текстом. */
export default function Tour({ module, onClose }: { module: TourModule; onClose: () => void }) {
  // Шаги, для которых элемента на экране нет, отбрасываем при старте (кроме шагов без селектора)
  const steps = useMemo(() => TOURS[module].filter(s => !s.selector || findTarget(s)), [module]);
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [cardH, setCardH] = useState(180);
  const step = steps[i];
  const last = i === steps.length - 1;

  // Шаг читаем из ref: события прокрутки после перехода к новому шагу иначе мерили бы прежний элемент
  const stepRef = useRef(step);
  stepRef.current = step;
  const measure = useCallback(() => {
    const cur = stepRef.current;
    const el = cur && findTarget(cur);
    if (!el) { setRect(null); return; }
    const r = el.getBoundingClientRect();
    // высокие блоки (списки, спецификация) обрезаем по краям экрана, чтобы рамка была видна целиком
    const top = Math.max(PAD, r.top - PAD), left = Math.max(PAD, r.left - PAD);
    const bottom = Math.min(window.innerHeight - PAD, r.bottom + PAD), right = Math.min(window.innerWidth - PAD, r.right + PAD);
    setRect({ top, left, width: Math.max(0, right - left), height: Math.max(0, bottom - top) });
  }, []);

  // При смене шага подкручиваем страницу к элементу, затем меряем
  useLayoutEffect(() => {
    const el = step && findTarget(step);
    el?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    measure();
    const t = setTimeout(measure, 350); // после плавной прокрутки и подгрузки данных
    return () => clearTimeout(t);
  }, [step, measure]);

  useLayoutEffect(() => { if (cardRef.current) setCardH(cardRef.current.offsetHeight); }, [i, rect]);

  // Положение подсветки следует за прокруткой и изменением размеров окна
  useEffect(() => {
    let raf = 0;
    const on = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(measure); };
    window.addEventListener('resize', on);
    window.addEventListener('scroll', on, true);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', on); window.removeEventListener('scroll', on, true); };
  }, [measure]);

  const next = useCallback(() => (last ? onClose() : setI(n => n + 1)), [last, onClose]);
  const back = useCallback(() => setI(n => Math.max(0, n - 1)), []);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); next(); }
      else if (e.key === 'ArrowLeft') back();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [next, back, onClose]);

  useEffect(() => { cardRef.current?.focus(); }, [i]);

  if (!step) return null;

  // Карточка: под элементом, если не влезает — над ним, иначе сбоку; на узком экране — внизу экрана
  const vw = window.innerWidth, vh = window.innerHeight;
  const narrow = vw < 640;
  let cardStyle: React.CSSProperties;
  if (narrow || !rect) {
    cardStyle = narrow
      ? { left: 12, right: 12, bottom: 12 }
      : { left: (vw - CARD_W) / 2, top: Math.max(24, (vh - cardH) / 2), width: CARD_W };
  } else {
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - CARD_W / 2), vw - CARD_W - 12);
    if (rect.top + rect.height + GAP + cardH < vh - 12) cardStyle = { left, top: rect.top + rect.height + GAP, width: CARD_W };
    else if (rect.top - GAP - cardH > 12) cardStyle = { left, top: rect.top - GAP - cardH, width: CARD_W };
    else {
      const side = rect.left + rect.width + GAP + CARD_W < vw - 12 ? rect.left + rect.width + GAP : Math.max(12, rect.left - GAP - CARD_W);
      cardStyle = { left: side, top: Math.min(Math.max(12, rect.top), vh - cardH - 12), width: CARD_W };
    }
  }

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={`Подсказка: ${step.title}`}>
      {/* клики мимо карточки не проходят в интерфейс, чтобы случайно ничего не нажать */}
      <div className="tour__blocker" onClick={e => e.stopPropagation()} />
      {rect ? (
        <>
          {/* затемнение — четыре полосы вокруг блока (надёжнее огромной тени) */}
          <div className="tour__dim" style={{ top: 0, left: 0, right: 0, height: rect.top }} />
          <div className="tour__dim" style={{ top: rect.top + rect.height, left: 0, right: 0, bottom: 0 }} />
          <div className="tour__dim" style={{ top: rect.top, left: 0, width: rect.left, height: rect.height }} />
          <div className="tour__dim" style={{ top: rect.top, left: rect.left + rect.width, right: 0, height: rect.height }} />
          <div className="tour__spot" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
        </>
      ) : <div className="tour__dim" style={{ inset: 0 }} />}
      <div ref={cardRef} className="tour__card" style={cardStyle} tabIndex={-1}>
        <div className="tour__step">{i + 1} из {steps.length}</div>
        <h3 className="tour__title">{step.title}</h3>
        <p className="tour__text">{step.text}</p>
        <div className="tour__actions">
          <button className="link-btn" onClick={onClose}>{last ? 'Закрыть' : 'Пропустить'}</button>
          <span className="tour__nav">
            {i > 0 && <button className="rt-btn rt-btn--ghost rt-btn--sm" onClick={back}>Назад</button>}
            <button className="rt-btn rt-btn--primary rt-btn--sm" onClick={next}>{last ? 'Готово' : 'Далее'}</button>
          </span>
        </div>
      </div>
    </div>
  );
}
