import logo from '../../assets/brand/rt-logo.svg';
import RadarPage from './radar/RadarPage';

export default function App() {
  return (
    <div className="app">
      <header className="header">
        <div className="header__top">
          <img src={logo} alt="Ростелеком" width={140} height={36} />
          <span className="header__product">Коммерческий блок</span>
          <span className="header__right">
            <span className="region">Ростовская область</span>
            <span className="avatar" title="Менеджер B2B">МП</span>
          </span>
        </div>
        <nav className="tabs" aria-label="Модули">
          <a className="rt-tab rt-tab--active" href="#radar">Радар присутствия</a>
          <a className="rt-tab rt-tab--soon" title="в разработке">Инвестиционный навигатор</a>
          <a className="rt-tab rt-tab--soon" title="в разработке">Калькулятор сделок</a>
        </nav>
      </header>
      <main><RadarPage /></main>
    </div>
  );
}
