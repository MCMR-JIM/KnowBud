import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import KidsLearning from './pages/KidsLearning';
import AdminDashboard from './pages/AdminDashboard'; // 🌟 引入刚写的真实页面

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/kids" element={<KidsLearning />} />
        <Route path="/admin" element={<AdminDashboard />} /> {/* 🌟 替换掉占位符 */}
      </Routes>
    </BrowserRouter>
  );
}

export default App;