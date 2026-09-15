import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

export default function CommandSuggestionsPanel() {
  const [categories, setCategories] = useState([]);
  const [commands, setCommands] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [isSeeding, setIsSeeding] = useState(false);

  const fetchCategories = async () => {
    try {
      const data = await apiClient.getJson('/commands/categories');
      setCategories(data.categories || []);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchCommands = async () => {
    try {
      let url = '/commands/suggestions?';
      if (selectedCategory) url += `category=${encodeURIComponent(selectedCategory)}&`;
      if (searchQuery) url += `query=${encodeURIComponent(searchQuery)}`;
      
      const data = await apiClient.getJson(url);
      setCommands(data.commands || []);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchCategories();
    fetchCommands();
  }, [selectedCategory, searchQuery]);

  const handleSeed = async () => {
    setIsSeeding(true);
    try {
      const data = await apiClient.postJson('/commands/seed-defaults', {});
      alert(data.message);
      fetchCommands();
    } catch (err) {
      alert(`Failed to seed commands: ${err.message}`);
    }
    setIsSeeding(false);
  };

  const handleCopy = async (cmd) => {
    try {
      await navigator.clipboard.writeText(cmd);
      alert(`Copied to clipboard:\n${cmd}`);
    } catch (err) {
      alert("Failed to copy command.");
    }
  };

  const getRiskColor = (risk) => {
    if (risk === 'low') return '#28a745';
    if (risk === 'medium') return '#ffc107';
    if (risk === 'high') return '#dc3545';
    return '#6c757d';
  };

  return (
    <Section title="Command Suggestions" description="Browse and copy safe terminal commands for Docker, Ollama, and Troubleshooting." >
      
      <div style={{display: 'flex', gap: '15px', marginBottom: '20px', alignItems: 'center', flexWrap: 'wrap'}}>
        <input 
          type="text" 
          placeholder="Search commands..." 
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{padding: '8px', borderRadius: '4px', flex: 1, minWidth: '200px'}}
        />
        
        <select 
          value={selectedCategory} 
          onChange={(e) => setSelectedCategory(e.target.value)}
          style={{padding: '8px', borderRadius: '4px', minWidth: '150px'}}
        >
          <option value="">All Categories</option>
          {categories.map(c => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
          ))}
        </select>
        
        <button 
          onClick={handleSeed} 
          disabled={isSeeding}
          style={{padding: '8px 12px', borderRadius: '4px', cursor: 'pointer'}}
        >
          {isSeeding ? 'Seeding...' : 'Seed Default Commands'}
        </button>
      </div>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '15px'}}>
        {commands.length === 0 ? (
          <p style={{fontSize: '13px'}}>No commands found.</p>
        ) : (
          commands.map(cmd => (
            <div key={cmd.id} style={{padding: '15px', borderRadius: '8px', display: 'flex', flexDirection: 'column'}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px'}}>
                <h4 style={{margin: 0, fontSize: '14px'}}>{cmd.title}</h4>
                <span style={{fontSize: '10px', padding: '2px 6px', borderRadius: '10px', fontWeight: 'bold', textTransform: 'uppercase'}}>
                  {cmd.risk_level}
                </span>
              </div>
              
              <div style={{fontSize: '12px', marginBottom: '10px', fontStyle: 'italic', flex: 1}}>
                {cmd.description}
              </div>

              <div style={{padding: '10px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                <code style={{wordBreak: 'break-all'}}>{cmd.command}</code>
                <button 
                  onClick={() => handleCopy(cmd.command)} 
                  style={{borderRadius: '3px', cursor: 'pointer', padding: '4px 8px', fontSize: '11px', marginLeft: '10px'}}
                >
                  Copy
                </button>
              </div>
              <div style={{fontSize: '10px', marginTop: '8px', textAlign: 'right'}}>
                Category: {cmd.category}
              </div>
            </div>
          ))
        )}
      </div>

    </Section>
  );
}
