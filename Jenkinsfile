pipeline {
    agent any

    environment {
        COMPOSE_FILE = 'docker-compose.yaml'
        IMAGE_NAME = 'crypalgos-api'
    }

    stages {

        stage('Setup Environment') {
            steps {
                script {
                    // Load secret .env file from Jenkins credentials
                    withCredentials([file(credentialsId: 'api_prod_env', variable: 'API_PROD_ENV_FILE')]) {
                        sh '''
                            cp $API_PROD_ENV_FILE .env.prod
                            chmod 600 .env.prod
                        '''
                    }

                    // Quick check (safe)
                    sh 'ls -la .env.prod'
                }
            }
        }

        stage('Build and Deploy') {
            steps {
                script {
                    sh '''
                        docker compose -f $COMPOSE_FILE up -d --build --remove-orphans
                    '''
                }
            }
        }

        stage('Cleanup') {
            steps {
                script {
                    sh '''
                        docker image prune -f
                    '''
                }
            }
        }
    }

    post {
        always {
            sh 'rm -f .env.prod'
        }
        success {
            echo '✅ Deployment successful!'
        }
        failure {
            echo '❌ Deployment failed!'
        }
    }
}
