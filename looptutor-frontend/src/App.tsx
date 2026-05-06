import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import KidsLearning from './pages/KidsLearning';
import AdminDashboard from './pages/AdminDashboard';
import ModeSelect from './pages/ModeSelect'; // 🌟 新增：模式选择页
import StudyRoom from './pages/StudyRoom';   // 🌟 新增：沉浸式学习主界面

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/kids" element={<KidsLearning />} />
        <Route path="/admin" element={<AdminDashboard />} />
        
        {/* V2 升级新增路由 */}
        <Route path="/select" element={<ModeSelect />} />
        <Route path="/study" element={<StudyRoom />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;