// src/pages/ParentDashboard.jsx
import React, { useState, useEffect } from 'react';
import { pushTaskToChild, fetchReviewQueue, fetchChartData } from '../api/parentApi';
// 引入 Recharts 图表组件
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useAppDialog } from '../components/AppDialog';

const ParentDashboard = () => {
  const appDialog = useAppDialog();
  const [reviewQueue, setReviewQueue] = useState([]);
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(false);

  // 初始化加载数据
  useEffect(() => {
    const loadData = async () => {
      try {
        const queueData = await fetchReviewQueue();
        setReviewQueue(queueData.items || []);

        const charts = await fetchChartData();
        // 假设 mastery 接口返回了类似 [{ date: '周一', score: 85 }, ...] 的数组
        // 如果后端格式不同，你需要在这里做一层数据转换 (map)
        setChartData(charts.mastery); 
      } catch (error) {
        console.error("初始化数据加载失败", error);
      }
    };
    loadData();
  }, []);

  // 处理推送任务
  const handlePush = async () => {
    setLoading(true);
    try {
      const result = await pushTaskToChild('topic_demo_01');
      await appDialog.alert(`推送成功！队列大小更新为: ${result.review_queue_size}`, { title: '推送成功', intent: 'success' });
      
      // 推送后刷新队列
      const updatedQueue = await fetchReviewQueue();
      setReviewQueue(updatedQueue.items || []);
    } catch (error) {
      await appDialog.alert("推送失败，请检查后端运行状态或控制台报错", { title: '推送失败', intent: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h1>家长端控制台</h1>

      <section style={{ marginBottom: '40px' }}>
        <h2>1. 任务推送</h2>
        <button 
          onClick={handlePush} 
          disabled={loading}
          style={{ padding: '10px 20px', cursor: 'pointer' }}
        >
          {loading ? '推送中...' : '向孩子推送演示任务 (topic_demo_01)'}
        </button>
      </section>

      <section style={{ marginBottom: '40px' }}>
        <h2>2. 当前资源调用（复习队列）</h2>
        {reviewQueue.length === 0 ? (
          <p>当前队列为空</p>
        ) : (
          <ul>
            {reviewQueue.map(item => (
              <li key={item.topic_id}>
                <strong>{item.title}</strong> - 包含 {item.resource_count} 个资源
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={{ height: '300px' }}>
        <h2>3. 掌握度图表展示</h2>
        {chartData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" /> {/* 这里的 dataKey 需根据你们后端实际返回的字段名调整 */}
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="score" stroke="#8884d8" activeDot={{ r: 8 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p>图表数据加载中...</p>
        )}
      </section>
    </div>
  );
};

export default ParentDashboard;
