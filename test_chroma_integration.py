import sys
import os
import numpy as np

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.vector_memory import VectorMemory
from skills.memory_manager import MemoryManager

def test_vector_memory():
    print("--- Testing VectorMemory (ChromaDB) ---")
    vm = VectorMemory()
    
    # Check initialization
    assert vm.chroma_client is not None, "ChromaDB client should be initialized"
    assert vm.memories_collection is not None, "Memories collection should be initialized"
    
    # Add memory
    text_mem = "Chinmay loves coding offline AI assistants on Windows."
    success = vm.add_memory(text_mem, category="personal_fact")
    print(f"Add memory success: {success}")
    assert success, "Should successfully save memory"
    
    # Semantic Search
    results = vm.semantic_search("What does Chinmay like to do?", limit=1)
    print(f"Semantic search results: {results}")
    assert len(results) > 0, "Should return at least one semantic match"
    match_sim, match_text, match_cat = results[0]
    print(f"Best match (similarity {match_sim:.3f}): '{match_text}' [{match_cat}]")
    assert "Chinmay" in match_text, "Returned text should match the expected content"

def test_face_embeddings_chroma():
    print("\n--- Testing Face Embeddings in ChromaDB ---")
    mm = MemoryManager()
    
    # Create a mock 4096-dimensional face embedding (flat vector)
    mock_emb = np.random.rand(64, 64)
    # Norm it like FaceEmbedder
    mock_emb_flat = mock_emb.flatten().astype(np.float32) / 255.0
    norm = np.linalg.norm(mock_emb_flat)
    if norm > 0:
        mock_emb_flat = mock_emb_flat / norm
    
    # Save face embedding
    # We will insert it directly to avoid needing camera/image frames
    user = "test_user_chroma"
    mm.known_faces[user] = mock_emb_flat.tolist()
    
    # Sync to ChromaDB
    if mm.vector_mem.faces_collection:
        mm.vector_mem.faces_collection.upsert(
            embeddings=[mock_emb_flat.tolist()],
            metadatas=[{"username": user}],
            ids=[user]
        )
        print("Upserted mock face embedding to ChromaDB.")
        
        # Test identify user
        # We query with the exact same embedding, similarity should be ~1.0
        results = mm.vector_mem.faces_collection.query(
            query_embeddings=[mock_emb_flat.tolist()],
            n_results=1
        )
        assert results and 'ids' in results and results['ids'][0], "Should find match in ChromaDB"
        best_match = results['ids'][0][0]
        dist = results['distances'][0][0]
        sim = 1.0 - dist
        print(f"ChromaDB Query Best Match: '{best_match}' with similarity: {sim:.3f}")
        assert best_match == user, f"Match should be {user}"
        assert sim > 0.99, "Similarity of exact match should be ~1.0"
        
        # Cleanup
        mm.vector_mem.faces_collection.delete(ids=[user])
        if user in mm.known_faces:
            del mm.known_faces[user]
        print("Cleaned up mock face embedding from ChromaDB.")
        
    print("Face embedding testing passed.")

if __name__ == "__main__":
    try:
        test_vector_memory()
        test_face_embeddings_chroma()
        print("\nAll integration tests passed successfully!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nIntegration test failed: {e}")
