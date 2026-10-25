import { useEffect, useState } from 'react';
import logo from '../../assets/brand/rt-logo.svg';
import { useUser } from './auth/AuthGate';
import UserMenu from './auth/UserMenu';
import CalcPage from './calc/CalcPage';
import InvestPage from './invest/InvestPage';
import ProfilePage from './profile/ProfilePage';
import RadarPage from './radar/RadarPage';
import Tour from './tour/Tour';

type Module = 'radar' | 'invest' | 'calc' | 'profile';
const fromHash = (h: string): Module =>
  (h.startsWith('#invest') ? 'invest' : h.startsWith('#calc') ? 'calc' : h.startsWith('#profile') ? 'profile' : 'radar');
const TITLES: Record<Module, string> = {
  radar: 'Радар присутствия', invest: 'Инвестиционный навигатор', calc: 'Калькулятор сделок', profile: 'Профиль',
};

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  const module = fromHash(hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  useEffect(() => {
    document.title = `${TITLES[module]} - Ростелеком`;
  }, [module]);

  // Обучалка: своя на каждой вкладке; лампочка мигает, пока подсказки этой вкладки ещё не смотрели
  const [tourOpen, setTourOpen] = useState(false);
  const [tourSeen, setTourSeen] = useState<Record<string, boolean>>(() => {
    try { return JSON.parse(localStorage.getItem('tour.seen.v1') ?? '{}'); } catch { return {}; }
  });
  useEffect(() => setTourOpen(false), [module]);
  // Первый вход или гость: подсвечиваем лампочку и предлагаем пройти подсказки (один раз за сеанс вкладки браузера)
  const user = useUser();
  const [prompt, setPrompt] = useState(() => {
    try { return user.first_login && !sessionStorage.getItem('tour.prompt.v1'); } catch { return user.first_login; }
  });
  const closePrompt = () => {
    setPrompt(false);
    try { sessionStorage.setItem('tour.prompt.v1', '1'); } catch { /* приватный режим */ }
  };
  const startTour = () => {
    closePrompt();
    setTourOpen(true);
    const seen = { ...tourSeen, [module]: true };
    setTourSeen(seen);
    try { localStorage.setItem('tour.seen.v1', JSON.stringify(seen)); } catch { /* приватный режим */ }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header__top">
          <img src={logo} alt="Ростелеком" width={140} height={36} />
          <span className="header__right">
            <span className="tour-anchor">
            <button className={`tour-btn ${tourSeen[module] ? '' : 'tour-btn--new'} ${prompt ? 'tour-btn--lit' : ''}`} onClick={startTour}
              title="Как пользоваться этой вкладкой" aria-label={`Подсказки: ${TITLES[module]}`}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M9 18h6M10 21h4" />
                <path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z" />
              </svg>
            </button>
            {prompt && !tourOpen && (
              <div className="tour-prompt" role="dialog" aria-label="Подсказки по интерфейсу">
                <b>{user.role === 'guest' ? 'Вы вошли гостем' : 'Впервые здесь?'}</b>
                <p>Пройдите подсказки - за минуту покажем, где что на вкладке «{TITLES[module]}». Позже их можно открыть этой лампочкой на любой вкладке</p>
                <div className="tour-prompt__actions">
                  <button className="rt-btn rt-btn--primary rt-btn--sm" onClick={startTour}>Пройти подсказки</button>
                  <button className="link-btn" onClick={closePrompt}>Позже</button>
                </div>
              </div>
            )}
            </span>
            {user.role === 'guest' && <span className="guest-chip" title="Гостевой режим: профиль недоступен">Гость</span>}
            <span className="region">Ростовская область</span>
            <UserMenu />
          </span>
        </div>
        <nav className="tabs" aria-label="Модули">
          <a className={`rt-tab ${module === 'radar' ? 'rt-tab--active' : ''}`} href="#radar"><span className="tab-full">Радар присутствия</span><span className="tab-short">Радар</span></a>
          <a className={`rt-tab ${module === 'invest' ? 'rt-tab--active' : ''}`} href="#invest"><span className="tab-full">Инвестиционный навигатор</span><span className="tab-short">Инвестпроекты</span></a>
          <a className={`rt-tab ${module === 'calc' ? 'rt-tab--active' : ''}`} href="#calc"><span className="tab-full">Калькулятор сделок</span><span className="tab-short">Калькулятор</span></a>
        </nav>
      </header>
      {/* Модули монтируются по отдельности: у каждого своя карта 2ГИС, держать две сразу незачем.
          Калькулятор пересоздаётся при переходе с новым проектом или компанией (#calc?project=…) */}
      <main>{module === 'radar' ? <RadarPage /> : module === 'invest' ? <InvestPage /> : module === 'profile' ? <ProfilePage />
        : <CalcPage key={hash} />}</main>
      {tourOpen && <Tour key={module} module={module} onClose={() => setTourOpen(false)} />}
    </div>
  );
}
