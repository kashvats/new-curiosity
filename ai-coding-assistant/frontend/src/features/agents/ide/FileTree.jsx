import React, { useState } from 'react';

function TreeNode({ node, level, onSelectFile, selectedFile }) {
  const [expanded, setExpanded] = useState(false);

  const isSelected = selectedFile === node.path;
  const isDir = node.is_dir;

  const handleClick = () => {
    if (isDir) {
      setExpanded(!expanded);
    } else {
      onSelectFile(node.path);
    }
  };

  return (
    <div>
      <div 
        onClick={handleClick}
        className={`tree-node ${isSelected ? 'selected' : ''}`}
        style={{
          paddingLeft: `${level * 15 + 10}px`
        }}
      >
        <span className="tree-icon">
          {isDir ? (expanded ? '📂' : '📁') : '📄'}
        </span>
        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {node.name}
        </span>
      </div>
      {isDir && expanded && node.children && (
        <div>
          {node.children.map(child => (
            <TreeNode 
              key={child.path} 
              node={child} 
              level={level + 1} 
              onSelectFile={onSelectFile} 
              selectedFile={selectedFile} 
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileTree({ tree, onSelectFile, selectedFile }) {
  if (!tree || tree.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>No files found.</div>;
  }

  return (
    <div>
      {tree.map(node => (
        <TreeNode 
          key={node.path} 
          node={node} 
          level={0} 
          onSelectFile={onSelectFile} 
          selectedFile={selectedFile} 
        />
      ))}
    </div>
  );
}
