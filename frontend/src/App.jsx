import React, { useState } from 'react';
import axios from 'axios';
import { Container, Row, Col, Alert, Spinner, Button, Form } from 'react-bootstrap';
import 'bootstrap/dist/css/bootstrap.min.css';
import './App.css';

function App() {
  const [analysisId, setAnalysisId] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [migrationResult, setMigrationResult] = useState(null);
  const [error, setError] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isMigrating, setIsMigrating] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState('');
  
  // New state for file upload
  const [selectedFile, setSelectedFile] = useState(null);
  const [projectPath, setProjectPath] = useState('');


  const apiBaseUrl = 'http://localhost:8000';

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setError('');
    setAnalysisResult(null);
    setMigrationResult(null);
    setDownloadUrl('');
    setIsAnalyzing(true);

    // Use FormData to send file and/or text fields
    const formData = new FormData();

    if (selectedFile) {
      formData.append('uploaded_file', selectedFile);
    } else if (projectPath) {
      formData.append('vb6_project_path', projectPath);
    } else {
      setError('Please provide a Git Repo URL or upload a project zip file.');
      setIsAnalyzing(false);
      return;
    }

    try {
      const response = await axios.post(`${apiBaseUrl}/analyze`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      setAnalysisResult(response.data); // The whole response is the result now
      if (response.data.analysis_id) {
        setAnalysisId(response.data.analysis_id);
      }
    } catch (err) {
      const errorMessage = err.response?.data?.detail ? JSON.stringify(err.response.data.detail) : err.message;
      setError('Analysis failed: ' + errorMessage);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleMigrate = async (e) => {
    e.preventDefault();
    setError('');
    setMigrationResult(null);
    setDownloadUrl('');
    setIsMigrating(true);
    
    // We get the modified architecture from the textarea
    const modifiedArchText = e.target.modifiedArch.value.trim();
    let modifiedArchPayload = null;
    
    // If the textarea is not empty, use its content.
    // Otherwise, use the architecture from the analysis result.
    if (modifiedArchText) {
      try {
        modifiedArchPayload = JSON.parse(modifiedArchText);
      } catch (jsonErr) {
        setError('Migration failed: The "Modified Architecture" is not valid JSON. Please correct it or leave it empty.');
        setIsMigrating(false);
        return;
      }
    } else if (analysisResult && analysisResult.proposed_architecture) {
      modifiedArchPayload = analysisResult.proposed_architecture;
    } else {
       setError('Migration failed: No architecture to migrate. Please run analysis first.');
       setIsMigrating(false);
       return;
    }

    try {
      const payload = {
        analysis_id: analysisId,
        modified_architecture: modifiedArchPayload,
      };

      const response = await axios.post(`${apiBaseUrl}/migrate`, payload);
      setMigrationResult(response.data);

      if (response.data.zip_path) {
        const url = `${apiBaseUrl}/static/${response.data.zip_path}`;
        setDownloadUrl(url);
      }

    } catch (err) {
      const errorMessage = err.response?.data?.detail ? JSON.stringify(err.response.data.detail) : err.message;
      setError('Migration failed: ' + errorMessage);
    } finally {
      setIsMigrating(false);
    }
  };

  const handleFileChange = (e) => {
    setSelectedFile(e.target.files[0]);
    setProjectPath(''); // Clear path input when file is selected
  };

  const handlePathChange = (e) => {
    setProjectPath(e.target.value);
    setSelectedFile(null); // Clear file input when path is typed
  };

  return (
    <Container className="mt-5">
      <h1 className="text-center mb-4">VB6 to .NET Windows Service Migration</h1>
      {error && <Alert variant="danger">{error}</Alert>}

      <Row className="mt-4">
        {/* Analysis Column */}
        <Col md={6} className="card-column">
          <div className="card p-4">
            <h2 className="card-title">1. Analyze VB6 Project</h2>
            <Form onSubmit={handleAnalyze}>
              <Form.Group className="mb-3">
                <Form.Label>Git Repo URL or Local Path:</Form.Label>
                <Form.Control 
                  type="text" 
                  value={projectPath}
                  onChange={handlePathChange}
                  placeholder="e.g., https://github.com/user/repo.git"
                  disabled={!!selectedFile}
                />
              </Form.Group>
              
              <p className="text-center my-2">OR</p>

              <Form.Group className="mb-3">
                <Form.Label>Upload Project (.zip):</Form.Label>
                <Form.Control 
                  type="file"
                  accept=".zip"
                  onChange={handleFileChange}
                  disabled={!!projectPath}
                />
              </Form.Group>

              <Button type="submit" variant="primary" disabled={isAnalyzing || (!projectPath && !selectedFile)}>
                {isAnalyzing ? <><Spinner size="sm" /> Analyzing...</> : 'Analyze'}
              </Button>
            </Form>
            {analysisResult && (
              <div className="mt-4 result-box">
                <h4>Analysis Complete</h4>
                <p><strong>Analysis ID:</strong> {analysisResult.analysis_id}</p>
                <p>Architecture proposed. You can review/edit it in the migration panel before migrating.</p>
              </div>
            )}
          </div>
        </Col>

        {/* Migration Column */}
        <Col md={6} className="card-column">
          <div className="card p-4">
            <h2 className="card-title">2. Migrate Project</h2>
            <Form onSubmit={handleMigrate}>
              <Form.Group className="mb-3">
                <Form.Label>Analysis ID:</Form.Label>
                <Form.Control type="text" value={analysisId} readOnly />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Proposed/Modified Architecture JSON:</Form.Label>
                <Form.Control 
                  as="textarea"
                  name="modifiedArch"
                  rows="10"
                  placeholder="The proposed architecture will appear here after analysis. You can edit it before migrating."
                  defaultValue={analysisResult ? JSON.stringify(analysisResult.proposed_architecture, null, 2) : ''}
                />
              </Form.Group>
              <Button type="submit" variant="success" disabled={!analysisId || isMigrating}>
                {isMigrating ? <><Spinner size="sm" /> Migrating...</> : 'Migrate'}
              </Button>
            </Form>
            {migrationResult && (
              <div className="mt-4 result-box">
                <h4>Migration Result</h4>
                <Alert variant="success"><strong>Status:</strong> {migrationResult.status}</Alert>
                {downloadUrl && (
                  <div>
                    <a href={downloadUrl} className="btn btn-lg btn-success" download>
                      Download Migrated Project (.zip)
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        </Col>
      </Row>
    </Container>
  );
}

export default App;